from fastapi import APIRouter, Header
from fastapi.responses import Response
from typing import List, Literal, Optional
import pytz
from auth import auth_id
from error_middleware import handle_error
from lib.daily_reminders.registration_stats import (
    DailyReminderRegistrationStatsPreparer,
)
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from itgs import Itgs
from contextlib import asynccontextmanager
from starlette.concurrency import run_in_threadpool
import notifications.push.lib.token_stats
import users.lib.entitlements
import unix_dates
import stripe
import time
import os

router = APIRouter()


ERROR_409_TYPES = Literal[
    "has_active_stripe_subscription",
    "has_active_ios_subscription",
    "has_active_google_subscription",
    "has_active_promotional_subscription",
]

HAS_ACTIVE_STRIPE_SUBSCRIPTION_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_409_TYPES](
        type="has_active_stripe_subscription",
        message=(
            "You have an active stripe subscription. If you delete your account, "
            "it will be canceled but you will not be refunded for any remaining time. "
            "To cancel your subscription, go to your account page."
        ),
    ).json(),
    headers={
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": "no-store",
    },
    status_code=409,
)

HAS_ACTIVE_IOS_SUBSCRIPTION_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_409_TYPES](
        type="has_active_ios_subscription",
        message=(
            "You have an active ios subscription. If you delete your account, "
            "it will not be canceled unless you cancel it yourself. To "
            "cancel your subscription, follow the instructions at "
            "https://support.apple.com/en-us/HT202039"
        ),
    ).json(),
    headers={
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": "no-store",
    },
    status_code=409,
)

HAS_ACTIVE_GOOGLE_SUBSCRIPTION_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_409_TYPES](
        type="has_active_google_subscription",
        message=(
            "You have an active google subscription. If you delete your account, "
            "it will be canceled but you might not be refunded for any remaining time. "
            "To cancel your subscription, go to your Settings page."
        ),
    ).json(),
    headers={
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": "no-store",
    },
    status_code=409,
)

HAS_ACTIVE_PROMOTIONAL_SUBSCRIPTION_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_409_TYPES](
        type="has_active_promotional_subscription",
        message=(
            "You have an active promotional subscription. If you delete your account, "
            "you may not be able to recover it."
        ),
    ).json(),
    headers={
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": "no-store",
    },
    status_code=409,
)

ERROR_429_TYPES = Literal["too_many_requests"]

TOO_MANY_REQUESTS_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_429_TYPES](
        type="too_many_requests",
        message="You are doing that too much. Try again in a minute.",
    ).json(),
    headers={
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": "no-store",
        "Retry-After": "60",
    },
    status_code=429,
)

ERROR_503_TYPES = Literal["multiple_updates"]

MULTIPLE_UPDATES_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_503_TYPES](
        type="multiple_updates",
        message=(
            "There are multiple updates in progress or the account has "
            "already been deleted. Log back in and try again."
        ),
    ).json(),
    headers={
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": "no-store",
        "Retry-After": "60",
    },
    status_code=503,
)


@router.delete(
    "/account",
    status_code=204,
    responses={
        "409": {
            "description": "The user has an active subscription, but the 'force' query parameter is not set to true",
            "model": StandardErrorResponse[ERROR_409_TYPES],
        },
        "429": {
            "description": "You are doing that too much. Try again soon.",
            "model": StandardErrorResponse[ERROR_429_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def delete_account(force: bool, authorization: Optional[str] = Header(None)):
    """Permanently deletes the authorized users account. If the user has an active
    entitlement, the request will fail unless the 'force' query parameter is set
    to true, which should only be done after confirming with the impact of deleting
    their account while they have an active entitlement.

    This requires id token authorization via the standard Authorization header.
    """
    async with Itgs() as itgs:
        auth_result = await auth_id(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        async with delete_lock(itgs, auth_result.result.sub) as got_lock:
            if not got_lock:
                return TOO_MANY_REQUESTS_RESPONSE

            conn = await itgs.conn()
            cursor = conn.cursor("weak")

            response = await cursor.execute(
                """
                SELECT 
                  users.revenue_cat_id,
                  stripe_customers.stripe_customer_id
                FROM users 
                LEFT OUTER JOIN stripe_customers ON users.id = stripe_customers.user_id
                WHERE 
                    users.sub = ?
                """,
                (auth_result.result.sub,),
            )
            if not response.results:
                return MULTIPLE_UPDATES_RESPONSE

            revenue_cat_id: str = response.results[0][0]
            stripe_customer_id: Optional[str] = response.results[0][1]
            revenue_cat = await itgs.revenue_cat()

            customer_info = await revenue_cat.get_customer_info(
                revenue_cat_id=revenue_cat_id
            )
            now = time.time()
            for (
                product_id,
                subscription,
            ) in customer_info.subscriber.subscriptions.items():
                is_active = (
                    subscription.expires_date is None
                    or subscription.expires_date.timestamp() > now
                )
                if is_active and not force:
                    if subscription.store == "app_store":
                        return HAS_ACTIVE_IOS_SUBSCRIPTION_RESPONSE
                    elif subscription.store == "play_store":
                        return HAS_ACTIVE_GOOGLE_SUBSCRIPTION_RESPONSE
                    elif subscription.store == "stripe":
                        return HAS_ACTIVE_STRIPE_SUBSCRIPTION_RESPONSE
                    else:
                        if subscription.store != "promotional":
                            slack = await itgs.slack()
                            await slack.send_web_error_message(
                                f"While deleting {auth_result.result.sub=}, {revenue_cat_id=}, found "
                                f"an active subscription with an unknown store: {subscription.store=}: "
                                "treating as promotional for the warning message",
                                "Unknown subscription store",
                            )

                        return HAS_ACTIVE_PROMOTIONAL_SUBSCRIPTION_RESPONSE

                if (
                    is_active
                    and subscription.unsubscribe_detected_at is None
                    and subscription.refunded_at is None
                ):
                    if subscription.store == "play_store":
                        # we may be less generous with refunds in the future if people
                        # abuse this
                        await revenue_cat.refund_and_revoke_google_play_subscription(
                            itgs, revenue_cat_id, product_id
                        )
                    elif subscription.store == "stripe":
                        if stripe_customer_id is None:
                            slack = await itgs.slack()
                            await slack.send_web_error_message(
                                f"While deleting {auth_result.result.sub=}, {revenue_cat_id=}, found "
                                f"an active subscription with store {subscription.store=}, but no "
                                f"stripe_customer_id: {stripe_customer_id=}. Preventing them from "
                                "deleting their account.",
                                "Delete stripe subscription with no stripe customer",
                            )
                            return MULTIPLE_UPDATES_RESPONSE

                        stripe_subscriptions = await run_in_threadpool(
                            stripe.Subscription.list,
                            customer=stripe_customer_id,
                            price=os.environ["OSEH_STRIPE_PRICE_ID"],
                            api_key=os.environ["OSEH_STRIPE_SECRET_KEY"],
                            limit=3,
                        )

                        if len(stripe_subscriptions) >= 3:
                            slack = await itgs.slack()
                            await slack.send_web_error_message(
                                f"While deleting {auth_result.result.sub=}, {revenue_cat_id=}, found "
                                f"an active subscription with store {subscription.store=}, but too many "
                                f"stripe subscriptions. Preventing them from deleting their account.",
                                "Delete stripe subscription with multiple stripe subscriptions",
                            )
                            return MULTIPLE_UPDATES_RESPONSE

                        # May be empty for a while after the cancellation before revenue cat
                        # processes the cancellation
                        for stripe_subscription in stripe_subscriptions:
                            await run_in_threadpool(
                                stripe.Subscription.delete,
                                stripe_subscription.id,
                                prorate=True,
                                api_key=os.environ["OSEH_STRIPE_SECRET_KEY"],
                            )

            await cleanup_user_daily_reminders(itgs, auth_result.result.sub)
            await cleanup_user_push_tokens(itgs, auth_result.result.sub)
            await cleanup_klaviyo(itgs, auth_result.result.sub)
            await cursor.execute(
                "DELETE FROM users WHERE sub=?", (auth_result.result.sub,)
            )

            redis = await itgs.redis()
            await redis.delete(
                f"oauth:valid_refresh_tokens:{auth_result.result.sub}".encode("utf-8"),
                f"entitlements:{auth_result.result.sub}".encode("utf-8"),
            )
            await users.lib.entitlements.publish_purge_message(
                itgs, user_sub=auth_result.result.sub, min_checked_at=time.time()
            )

            cache = await itgs.local_cache()
            cache.delete(f"users:{auth_result.result.sub}:created_at".encode("utf-8"))

            if os.environ["ENVIRONMENT"] != "dev":
                slack = await itgs.slack()
                await slack.send_ops_message(
                    f"Deleted {auth_result.result.sub=}, {revenue_cat_id=}, {stripe_customer_id=} by "
                    f"request from the user ({force=}). {os.environ.get('ENVIRONMENT')=}",
                    "Deleted user",
                )

            return Response(status_code=204)


async def cleanup_user_daily_reminders(itgs: Itgs, sub: str) -> None:
    """Cleans up any daily reminders the user has, in particular this also
    updates our daily reminder statistics

    Args:
        itgs (Itgs): the integrations to (re)use
        sub (str): the sub of the user whose daily reminders will be cleaned
            up
    """
    now = time.time()
    unix_date = unix_dates.unix_timestamp_to_unix_date(
        now, tz=pytz.timezone("America/Los_Angeles")
    )
    conn = await itgs.conn()
    cursor = conn.cursor()

    channels = ["sms", "email", "push"]

    response = await cursor.executemany3(
        tuple(
            (
                """
                DELETE FROM user_daily_reminders
                WHERE
                    EXISTS (
                        SELECT 1 FROM users 
                        WHERE 
                            users.id = user_daily_reminders.user_id
                            AND users.sub=?
                    )
                    AND user_daily_reminders.channel = ?
                """,
                (sub, channel),
            )
            for channel in channels
        )
    )

    deleted_by_channel = [
        res.rows_affected if res.rows_affected is not None else 0 for res in response
    ]

    if sum(deleted_by_channel) > 0:
        stats = DailyReminderRegistrationStatsPreparer()
        for channel, amt in zip(channels, deleted_by_channel):
            stats.incr_unsubscribed(unix_date, channel, "account_deleted", amt=amt)
        await stats.store(itgs)


async def cleanup_user_push_tokens(itgs: Itgs, sub: str) -> None:
    """Cleans up any push tokens the user has, in particular this updates
    our statistics for push tokens.

    Args:
        itgs (Itgs): The integrations to (re)use
        sub (str): The sub of the user whose push tokens will be cleaned up
    """
    conn = await itgs.conn()
    cursor = conn.cursor()
    response = await cursor.execute(
        """
        DELETE FROM user_push_tokens
        WHERE
            EXISTS (
                SELECT 1 FROM users
                WHERE users.id = user_push_tokens.user_id
                  AND users.sub = ?
            )
        """,
        (sub,),
    )
    if response.rows_affected is not None and response.rows_affected > 0:
        await notifications.push.lib.token_stats.increment_event(
            itgs,
            event="deleted_due_to_user_deletion",
            now=time.time(),
            amount=response.rows_affected,
        )


async def cleanup_klaviyo(itgs: Itgs, sub: str) -> None:
    """If the user has a klaviyo profile, their email is suppressed and we unsubscribe
    them from any lists we added them to.

    Args:
        itgs (Itgs): The integrations to (re)use
        sub (str): The sub of the user whose klaviyo profile will be cleaned up
    """
    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    response = await cursor.execute(
        """
        SELECT 
            user_klaviyo_profiles.klaviyo_id,
            user_klaviyo_profiles.email,
            user_klaviyo_profiles.phone_number,
            user_klaviyo_profile_lists.list_id
        FROM user_klaviyo_profiles
        LEFT OUTER JOIN user_klaviyo_profile_lists
            ON user_klaviyo_profile_lists.user_klaviyo_profile_id = user_klaviyo_profiles.id
        WHERE EXISTS (
            SELECT 1 FROM users
            WHERE users.id = user_klaviyo_profiles.user_id
              AND users.sub = ?
        )
        """,
        (sub,),
    )

    if not response.results:
        return

    klaviyo_id: str = response.results[0][0]
    email: str = response.results[0][1]
    phone_number: str = response.results[0][2]
    list_ids: List[str] = [row[3] for row in response.results if row[3] is not None]

    klaviyo = await itgs.klaviyo()
    try:
        await klaviyo.suppress_email(email)
    except Exception as e:
        await handle_error(
            e,
            extra_info=(
                f"failed to cleanup klaviyo account while deleting profile (suppress email); {sub=}, {klaviyo_id=}, {email=}, {phone_number=}, {list_ids=}"
            ),
        )
    try:
        for list_id in list_ids:
            await klaviyo.remove_from_list(profile_id=klaviyo_id, list_id=list_id)
    except Exception as e:
        await handle_error(
            e,
            extra_info=(
                f"failed to cleanup klaviyo account while deleting profile (remove from lists); {sub=}, {klaviyo_id=}, {email=}, {phone_number=}, {list_ids=}"
            ),
        )

    try:
        await klaviyo.request_profile_deletion(klaviyo_id)
    except Exception as e:
        await handle_error(
            e,
            extra_info=(
                f"failed to cleanup klaviyo account while deleting profile (request profile deletion); {sub=}, {klaviyo_id=}, {email=}, {phone_number=}, {list_ids=}"
            ),
        )


@asynccontextmanager
async def delete_lock(itgs: Itgs, sub: str) -> bool:
    """An asynchronous context manager that ensures only one delete operation can
    be performed at a time for a given user. Provides true if the lock was acquired,
    false if it was not.
    """
    key = f"users:{sub}:delete:lock".encode("utf-8")
    redis = await itgs.redis()

    got_lock = await redis.set(key, b"1", ex=60, nx=True)
    if not got_lock:
        yield False
        return

    try:
        yield True
    finally:
        await redis.delete(key)
