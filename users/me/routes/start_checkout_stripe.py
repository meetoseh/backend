import asyncio
import os
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, StringConstraints
from typing import Annotated, Any, Literal, Optional, cast
from auth import AuthResult, auth_id
from itgs import Itgs
from lib.contact_methods.user_current_email import get_user_current_email
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from starlette.concurrency import run_in_threadpool
from user_safe_error import UserSafeError
from error_middleware import handle_error
import users.lib.entitlements as entitlements
import users.lib.offerings as offerings
from users.lib.prices import Period
import stripe
import secrets
from urllib.parse import urlencode

from users.lib.stripe_prices import get_stripe_price
from users.lib.stripe_trials import is_user_stripe_trial_eligible


router = APIRouter()


class StartCheckoutStripeRequest(BaseModel):
    package_id: Annotated[
        Optional[str], StringConstraints(min_length=1, max_length=255)
    ] = Field(
        description="The RevenueCat package identifier to use, or None for default"
    )

    cancel_path: Literal["/upgrade", "/"] = Field(
        description=("The path to redirect to if the user cancels the checkout flow.")
    )

    success_path: Literal["/"] = Field(
        description=(
            "The path to redirect to if the user successfully completes the checkout flow. "
            "Will have query parameters added:\n"
            "- `checkout_success`: `1`\n"
            "- `checkout_uid`: The uid to pass back to the finish checkout endpoint"
        )
    )


class StartCheckoutStripeResponse(BaseModel):
    url: str = Field(
        description="The URL to redirect the user to in order to start the checkout flow."
    )


ERROR_409_TYPES = Literal["already_subscribed"]
ERROR_429_TYPES = Literal["ratelimited"]
ERROR_503_TYPES = Literal["user_not_found", "stripe_error"]


@router.post(
    "/checkout/stripe/start",
    response_model=StartCheckoutStripeResponse,
    responses={
        "409": {
            "model": StandardErrorResponse[ERROR_409_TYPES],
            "description": "The user already has the pro entitlement",
        },
        "429": {
            "model": StandardErrorResponse[ERROR_429_TYPES],
            "description": "The user has exceeded the rate limit for this endpoint.",
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def start_checkout_stripe(
    args: StartCheckoutStripeRequest, authorization: Optional[str] = Header(None)
):
    """Begins the checkout process for the pro entitlement via stripe. This
    requires id token authentication and is ratelimited.

    The checkout session should not be registered with revenue cat until the
    session is actually completed, so the client does not need to do anything
    with the session id. The checkout session will always eventually be
    registered with revenue cat, but the client can speed the process up with
    the finish_checkout_stripe endpoint.

    The success url will have the query parameter `checkout_success=1` added
    """
    async with Itgs() as itgs:
        auth_result = await auth_id(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        redis = await itgs.redis()
        ratelimit_success = await redis.set(
            f"checkout:stripe:start:ratelimit:{auth_result.result.sub}",
            1,
            ex=15,
            nx=True,
        )
        if not ratelimit_success:
            return Response(
                content=StandardErrorResponse[ERROR_429_TYPES](
                    type="ratelimited",
                    message="You have exceeded the rate limit for this endpoint.",
                ).model_dump_json(),
                status_code=429,
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Retry-After": "15",
                },
            )

        existing_entitlement = await entitlements.get_entitlement(
            itgs, user_sub=auth_result.result.sub, identifier="pro", force=True
        )
        assert existing_entitlement is not None, auth_result

        if existing_entitlement.is_active:
            return Response(
                content=StandardErrorResponse[ERROR_409_TYPES](
                    type="already_subscribed",
                    message="You already have the pro entitlement.",
                ).model_dump_json(),
                status_code=409,
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        try:
            customer_id, is_trial_eligible = await asyncio.gather(
                ensure_stripe_customer(itgs, auth_result),
                is_user_stripe_trial_eligible(
                    itgs, user_sub=auth_result.result.sub, now=time.time()
                ),
            )
        except UserSafeError as exc:
            return exc.response

        stripe_price_info = CachedStripePriceInfo(
            trial=None,
            price_id=os.environ["OSEH_STRIPE_PRICE_ID"],
        )
        if args.package_id is not None:
            user_offerings = await offerings.get_offerings(
                itgs, user_sub=auth_result.result.sub, platform="stripe", force=False
            )
            stripe_product_id = None
            if user_offerings is not None:
                for offering in user_offerings.offerings:
                    if offering.identifier != user_offerings.current_offering_id:
                        continue
                    for package in offering.packages:
                        if package.identifier == args.package_id:
                            stripe_product_id = package.platform_product_identifier
                            break
                    break

            if stripe_product_id is not None:
                try:
                    product_default_price_info = await get_default_stripe_price_info(
                        itgs, stripe_product_id=stripe_product_id
                    )
                except UserSafeError as exc:
                    return exc.response

                if product_default_price_info is not None:
                    stripe_price_info = product_default_price_info

        uid = f"oseh_oscs_{secrets.token_urlsafe(16)}"
        try:
            session = await run_in_threadpool(
                stripe.checkout.Session.create,
                api_key=os.environ["OSEH_STRIPE_SECRET_KEY"],
                customer=customer_id,
                success_url=(
                    os.environ["ROOT_FRONTEND_URL"]
                    + args.success_path
                    + "?"
                    + urlencode({"checkout_success": "1", "checkout_uid": uid})
                ),
                cancel_url=os.environ["ROOT_FRONTEND_URL"] + args.cancel_path,
                mode="subscription",
                allow_promotion_codes=True,
                line_items=[
                    {
                        "price": stripe_price_info.price_id,
                        "quantity": 1,
                    }
                ],
                **cast(
                    Any,
                    (
                        {
                            "subscription_data": {
                                "trial_period_days": stripe_price_info.trial.in_days()
                            }
                        }
                        if is_trial_eligible and stripe_price_info.trial is not None
                        else {}
                    ),
                ),
            )
        except Exception as exc:
            await handle_error(exc)
            raise UserSafeError(
                f"Failed to create checkout session for {auth_result.result.sub=}",
                Response(
                    content=StandardErrorResponse[ERROR_503_TYPES](
                        type="stripe_error",
                        message="There was an error communicating with our payment provider.",
                    ).model_dump_json(),
                    headers={
                        "Content-Type": "application/json; charset=utf-8",
                        "Retry-After": "5",
                    },
                ),
            )

        async def cancel_session():
            await run_in_threadpool(
                stripe.checkout.Session.expire,
                session.id,
                api_key=os.environ["OSEH_STRIPE_SECRET_KEY"],
            )

        try:
            assert session.url is not None, session
            await store_session(
                itgs,
                checkout_session_id=session.id,
                user_sub=auth_result.result.sub,
                expires_at=(
                    hasattr(session, "expires_at")
                    and session.expires_at
                    or int(time.time() + 86401)
                ),
                uid=uid,
            )

            return StartCheckoutStripeResponse(url=session.url)
        except UserSafeError as exc:
            await cancel_session()
            return exc.response
        except Exception:
            await cancel_session()
            raise


async def ensure_stripe_customer(itgs: Itgs, auth_result: AuthResult) -> str:
    """Gets or creates and gets the stripe customer id to use for the
    given user.
    """
    assert auth_result.result is not None
    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    response = await cursor.execute(
        """
        SELECT
            stripe_customers.stripe_customer_id
        FROM stripe_customers
        WHERE
            EXISTS (
                SELECT 1 FROM users
                WHERE users.id = stripe_customers.user_id
                  AND users.sub = ?
            )
        ORDER BY stripe_customers.created_at DESC, stripe_customers.uid ASC
        LIMIT 1
        """,
        (auth_result.result.sub,),
    )
    if response.results:
        return response.results[0][0]

    email = await get_user_current_email(itgs, auth_result, default=None)
    response = await cursor.execute(
        """
        SELECT
            users.given_name,
            users.family_name
        FROM users WHERE users.sub = ?
        """,
        (auth_result.result.sub,),
    )
    if not response.results:
        raise UserSafeError(
            f"`{auth_result.result.sub=}` does not exist",
            Response(
                content=StandardErrorResponse[ERROR_503_TYPES](
                    type="user_not_found",
                    message="Despite valid authorization, you do not appear to exist! Your account may have been deleted.",
                ).model_dump_json(),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Retry-After": "15",
                },
            ),
        )

    given_name, family_name = response.results[0]
    name = f"{given_name} {family_name}"

    try:
        customer = await run_in_threadpool(
            stripe.Customer.create,
            api_key=os.environ["OSEH_STRIPE_SECRET_KEY"],
            name=name,
            metadata={
                "user_sub": auth_result.result.sub,
                "created_for": "start_checkout_stripe",
            },
            **({"email": email} if email is not None else {}),  # type: ignore
        )
    except Exception as exc:
        await handle_error(exc)
        raise UserSafeError(
            f"Failed to create stripe customer for {auth_result.result.sub=}",
            Response(
                content=StandardErrorResponse[ERROR_503_TYPES](
                    type="stripe_error",
                    message="There was an error communicating with our payment provider.",
                ).model_dump_json(),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Retry-After": "5",
                },
            ),
        )

    await cursor.execute(
        """
        INSERT INTO stripe_customers (
            uid,
            stripe_customer_id,
            user_id,
            created_at
        )
        SELECT
            ?, ?, users.id, ?
        FROM users WHERE users.sub = ?
        """,
        (
            f"oseh_sc_{secrets.token_urlsafe(16)}",
            customer.id,
            time.time(),
            auth_result.result.sub,
        ),
    )

    return customer.id


async def store_session(
    itgs: Itgs, *, checkout_session_id: str, user_sub: str, expires_at: float, uid: str
) -> None:
    """Stores the given checkout session id in the database so that
    we will periodically check if it completed.

    Args:
        itgs (Itgs): The connections for networked services
        checkout_session_id (str): The id of the checkout session
        user_sub (str): The sub of the user who started the checkout
        expires_at (float): The unix timestamp at which the session expires
        uid (str): The UID for the row to create
    """
    conn = await itgs.conn()
    cursor = conn.cursor("none")

    now = time.time()
    await cursor.execute(
        """
        INSERT INTO open_stripe_checkout_sessions (
            uid,
            stripe_checkout_session_id,
            user_id,
            last_checked_at,
            created_at,
            expires_at
        )
        SELECT
            ?, ?, users.id, ?, ?, ?
        FROM users WHERE users.sub = ?
        """,
        (
            uid,
            checkout_session_id,
            now,
            now,
            expires_at,
            user_sub,
        ),
    )


class CachedStripePriceInfo(BaseModel):
    trial: Optional[Period] = Field()
    price_id: str = Field()


async def get_default_stripe_price_info(
    itgs: Itgs, /, *, stripe_product_id: str
) -> Optional[CachedStripePriceInfo]:
    """Fetches the default stripe price id associated with the stripe product
    with the given id.
    """
    try:
        price = await get_stripe_price(itgs, product_id=stripe_product_id)
    except Exception as exc:
        await handle_error(exc, extra_info=f"fetching prices for {stripe_product_id=}")
        raise UserSafeError(
            f"failed to fetch prices for {stripe_product_id=}",
            Response(
                content=StandardErrorResponse[ERROR_503_TYPES](
                    type="stripe_error",
                    message="There was an error communicating with our payment provider.",
                ).model_dump_json(),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Retry-After": "5",
                },
            ),
        )

    if price is None:
        raise UserSafeError(
            f"failed to fetch prices for {stripe_product_id=}",
            Response(
                content=StandardErrorResponse[ERROR_503_TYPES](
                    type="stripe_error",
                    message="There was an error communicating with our payment provider.",
                ).model_dump_json(),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Retry-After": "5",
                },
            ),
        )

    trial_raw = price.metadata.get("trial", None)
    if trial_raw is not None and isinstance(trial_raw, str):
        trial = Period(iso8601=trial_raw)
    else:
        trial = None

    return CachedStripePriceInfo(trial=trial, price_id=price.id)
