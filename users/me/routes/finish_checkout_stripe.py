import asyncio
from typing import Literal, Optional
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from error_middleware import handle_error
from itgs import Itgs
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from auth import auth_id
from starlette.concurrency import run_in_threadpool
import stripe
import os
import time

from users.me.routes.read_revenue_cat_id import get_revenue_cat_id


class FinishCheckoutStripeRequest(BaseModel):
    checkout_uid: str = Field(
        description=(
            "The UID of the completed checkout, from `start_checkout_stripe`: "
            "this will only be available when the checkout completes successfully, "
            "and will be provided in the query parameters to the success path."
        )
    )


class FinishCheckoutStripeResponse(BaseModel):
    ...


router = APIRouter()


ERROR_404_TYPES = Literal["not_found"]
ERROR_409_TYPES = Literal["incomplete"]
ERROR_429_TYPES = Literal["ratelimited"]
ERROR_503_TYPES = Literal["stripe_error", "revenue_cat_error", "not_found"]


@router.post(
    "/checkout/stripe/finish",
    response_model=FinishCheckoutStripeResponse,
    responses={
        "404": {
            "model": StandardErrorResponse[ERROR_404_TYPES],
            "description": (
                "There is no open checkout with the given uid. It may have expired "
                "or have already been detected as finished, or be for a different "
                "user"
            ),
        },
        "409": {
            "model": StandardErrorResponse[ERROR_409_TYPES],
            "description": "The checkout was found but isn't complete yet.",
        },
        "429": {
            "model": StandardErrorResponse[ERROR_429_TYPES],
            "description": "The user has exceeded the rate limit for this endpoint.",
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def finish_checkout_stripe(
    args: FinishCheckoutStripeRequest, authorization: Optional[str] = Header(None)
):
    """Requests that the server check if the given checkout has completed. This
    is not required for the information to eventually be reconciled with the server,
    but it can be used to provide a better user experience by reducing the delay.

    This is only used for stripe, and requires id token authentication.
    """
    async with Itgs() as itgs:
        auth_result = await auth_id(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        redis = await itgs.redis()
        ratelimit_success = await redis.set(
            f"checkout:stripe:finish:ratelimit:{auth_result.result.sub}",
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

        conn = await itgs.conn()
        cursor = conn.cursor("weak")

        response = await cursor.execute(
            """
            SELECT
                open_stripe_checkout_sessions.stripe_checkout_session_id
            FROM open_stripe_checkout_sessions
            WHERE
                open_stripe_checkout_sessions.uid = ?
                AND EXISTS (
                    SELECT 1 FROM users
                    WHERE open_stripe_checkout_sessions.user_id = users.id
                      AND users.sub = ?
                )
            """,
            (args.checkout_uid, auth_result.result.sub),
        )
        if not response.results:
            return Response(
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="not_found",
                    message=(
                        "There is no open checkout with the given uid. The checkout may have "
                        "already been detected as completed, or it could have expired, or "
                        "it could be for a different user."
                    ),
                ).json(),
                status_code=404,
            )

        stripe_checkout_session_id: str = response.results[0][0]

        try:
            checkout_session = await run_in_threadpool(
                stripe.checkout.Session.retrieve,
                stripe_checkout_session_id,
                api_key=os.environ["OSEH_STRIPE_SECRET_KEY"],
            )
        except Exception as exc:
            await handle_error(exc)
            return Response(
                content=StandardErrorResponse[ERROR_503_TYPES](
                    type="stripe_error",
                    message=("There was an error communicating with Stripe"),
                ).json(),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Retry-After": "15",
                },
                status_code=503,
            )

        if checkout_session.status != "complete":
            cursor.execute(
                """
                UPDATE open_stripe_checkout_sessions
                SET last_checked_at=?
                WHERE uid=?
                """,
                (time.time(), args.checkout_uid),
            )
            return Response(
                content=StandardErrorResponse[ERROR_409_TYPES](
                    type="incomplete",
                    message="That checkout is not yet complete. You might need to wait a moment.",
                ).json(),
                status_code=409,
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        revenue_cat_id = await get_revenue_cat_id(itgs, auth_result.result.sub)
        if not isinstance(revenue_cat_id, str):
            return revenue_cat_id

        rc = await itgs.revenue_cat()
        try:
            await rc.create_stripe_purchase(
                revenue_cat_id=revenue_cat_id,
                stripe_checkout_session_id=stripe_checkout_session_id,
            )
        except Exception as exc:
            await handle_error(exc)
            return Response(
                content=StandardErrorResponse[ERROR_503_TYPES](
                    type="revenue_cat_error",
                    message=("There was an error communicating with RevenueCat"),
                ).json(),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Retry-After": "15",
                },
                status_code=503,
            )

        await cursor.execute(
            "DELETE FROM open_stripe_checkout_sessions WHERE uid=?",
            (args.checkout_uid,),
        )
        return Response(
            content=FinishCheckoutStripeResponse().json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=200,
        )
