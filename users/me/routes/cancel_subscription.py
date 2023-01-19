from fastapi import APIRouter, Header
from fastapi.responses import Response
from typing import Literal, Optional
from auth import auth_id
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from itgs import Itgs
from contextlib import asynccontextmanager
from starlette.concurrency import run_in_threadpool
from users.me.routes.delete_account import delete_lock
import users.lib.entitlements
import stripe
import time
import os


router = APIRouter()


ERROR_409_TYPES = Literal[
    "no_active_subscription",
    "has_active_ios_subscription",
    "has_active_promotional_subscription",
]


NO_ACTIVE_SUBSCRIPTION_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_409_TYPES](
        type="no_active_subscription", message="No active subscription found to cancel."
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
            "You have an active ios subscription. It must be canceled manually. "
            "To cancel your subscription, follow the instructions at "
            "https://support.apple.com/en-us/HT202039"
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
            "You have an active promotional subscription. It does not "
            "need to be canceled as it does not incur a charge."
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
            "There are multiple updates in progress, the account has "
            "already been deleted, or the subscription was just canceled. "
            "Log back in and try again."
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
    "/subscription",
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
async def cancel_subscription(authorization: Optional[str] = Header(None)):
    """Attempts to cancel the users subscription. Not all subscription providers
    support server-side subscription cancellation, so the client must detect and
    handle conflict errors by providing the appropriate steps to cancel the
    subscription manually.

    After this completes, the user may still have access to Oseh+ for up to a
    few hours after the subscription actually expires.

    This requires id token authorization via the standard authorization header.
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
            canceled_something = False
            for (
                product_id,
                subscription,
            ) in customer_info.subscriber.subscriptions.items():
                is_active = (
                    subscription.expires_date is None
                    or subscription.expires_date.timestamp() > now
                )
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
                        canceled_something = True
                    elif subscription.store == "stripe":
                        if stripe_customer_id is None:
                            slack = await itgs.slack()
                            await slack.send_web_error_message(
                                f"While canceling {auth_result.result.sub=}, {revenue_cat_id=}, found "
                                f"an active subscription with store {subscription.store=}, but no "
                                f"stripe_customer_id: {stripe_customer_id=}",
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
                                f"While canceling {auth_result.result.sub=}, {revenue_cat_id=}, found "
                                f"an active subscription with store {subscription.store=}, but too many "
                                f"stripe subscriptions.",
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
                            canceled_something = True
                    elif subscription.store == "app_store":
                        return HAS_ACTIVE_IOS_SUBSCRIPTION_RESPONSE
                    elif subscription.store == "promotional":
                        return HAS_ACTIVE_PROMOTIONAL_SUBSCRIPTION_RESPONSE
                    else:
                        slack = await itgs.slack()
                        await slack.send_web_error_message(
                            f"While canceling {auth_result.result.sub=}, {revenue_cat_id=}, found "
                            f"an active subscription with store {subscription.store=}, but no "
                            f"support for that store.",
                            "Delete subscription with unknown store",
                        )
                        return MULTIPLE_UPDATES_RESPONSE

            if not canceled_something:
                return NO_ACTIVE_SUBSCRIPTION_RESPONSE

            redis = await itgs.redis()
            await redis.delete(f"entitlements:{auth_result.result.sub}".encode("utf-8"))
            await users.lib.entitlements.publish_purge_message(
                itgs, user_sub=auth_result.result.sub, min_checked_at=time.time()
            )

            return Response(status_code=204)
