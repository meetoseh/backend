import os
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal, Optional
from auth import auth_id
from itgs import Itgs
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from starlette.concurrency import run_in_threadpool
from user_safe_error import UserSafeError
from error_middleware import handle_error
import users.lib.entitlements as entitlements
import stripe
import asyncio
import secrets
from urllib.parse import urlencode


router = APIRouter()


class StartCheckoutStripeRequest(BaseModel):
    cancel_path: Literal["/"] = Field(
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
        if not auth_result.success:
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
                ).json(),
                status_code=429,
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Retry-After": "15",
                },
            )

        existing_entitlement = await entitlements.get_entitlement(
            itgs, user_sub=auth_result.result.sub, identifier="pro", force=True
        )

        if existing_entitlement.is_active:
            return Response(
                content=StandardErrorResponse[ERROR_409_TYPES](
                    type="already_subscribed",
                    message="You already have the pro entitlement.",
                ).json(),
                status_code=409,
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        try:
            customer_id = await ensure_stripe_customer(itgs, auth_result.result.sub)
        except UserSafeError as exc:
            return exc.response

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
                line_items=[
                    {
                        "price": os.environ["OSEH_STRIPE_PRICE_ID"],
                        "quantity": 1,
                    }
                ],
            )
        except Exception as exc:
            await handle_error(exc)
            raise UserSafeError(
                f"Failed to create checkout session for {auth_result.result.sub=}",
                Response(
                    content=StandardErrorResponse[ERROR_503_TYPES](
                        type="stripe_error",
                        message="There was an error communicating with our payment provider.",
                    ).json(),
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


async def ensure_stripe_customer(itgs: Itgs, user_sub: str) -> str:
    """Gets or creates and gets the stripe customer id to use for the
    given user.
    """
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
        (user_sub,),
    )
    if response.results:
        return response.results[0][0]

    response = await cursor.execute(
        """
        SELECT
            users.email,
            users.given_name,
            users.family_name
        FROM users WHERE users.sub = ?
        """,
        (user_sub,),
    )
    if not response.results:
        raise UserSafeError(
            f"{user_sub=} does not exist",
            Response(
                content=StandardErrorResponse[ERROR_503_TYPES](
                    type="user_not_found",
                    message="Despite valid authorization, you do not appear to exist! Your account may have been deleted.",
                ).json(),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Retry-After": "15",
                },
            ),
        )

    email, given_name, family_name = response.results[0]
    name = f"{given_name} {family_name}"

    try:
        customer = await run_in_threadpool(
            stripe.Customer.create,
            api_key=os.environ["OSEH_STRIPE_SECRET_KEY"],
            email=email,
            name=name,
            metadata={"user_sub": user_sub, "created_for": "start_checkout_stripe"},
        )
    except Exception as exc:
        await handle_error(exc)
        raise UserSafeError(
            f"Failed to create stripe customer for {user_sub=}",
            Response(
                content=StandardErrorResponse[ERROR_503_TYPES](
                    type="stripe_error",
                    message="There was an error communicating with our payment provider.",
                ).json(),
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
        (f"oseh_sc_{secrets.token_urlsafe(16)}", customer.id, time.time(), user_sub),
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
