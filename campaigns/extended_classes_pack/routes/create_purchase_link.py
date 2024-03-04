import os
import secrets
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal, Optional

import stripe
from error_middleware import handle_error
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from auth import auth_any
from itgs import Itgs
from user_safe_error import UserSafeError
from users.lib.entitlements import get_entitlement
from users.me.routes.start_checkout_stripe import ensure_stripe_customer, store_session
from starlette.concurrency import run_in_threadpool


router = APIRouter()


class CreateExtendedClassesPackPurchaseLinkRequest(BaseModel):
    cancel_path: Literal["/"] = Field(
        description=("The path to redirect to if the user cancels the checkout flow.")
    )

    success_path: Literal["/courses/activate"] = Field(
        description=(
            "The path to redirect to if the user successfully completes the checkout flow. "
            "Will have query parameters added:\n"
            "- `slug`: The slug of the course to activate\n"
            "- `session`: The uid to pass back to the finish checkout endpoint"
        )
    )


class CreateExtendedClassesPackPurchaseLinkResponse(BaseModel):
    url: str = Field(
        description="The URL to redirect the user to in order to start the checkout flow."
    )


ERROR_409_TYPES = Literal["already_owned"]
ALREADY_OWNED_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_409_TYPES](
        type="already_owned", message="You already own the extended classes pack."
    ).model_dump_json(),
    status_code=409,
    headers={"Content-Type": "application/json; charset=utf-8"},
)

ERROR_503_TYPES = Literal["provider_error"]
PROVIDER_ERROR_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_503_TYPES](
        type="provider_error",
        message="There was an error communicating with the payment provider.",
    ).model_dump_json(),
    status_code=503,
    headers={"Content-Type": "application/json; charset=utf-8", "Retry-After": "60"},
)


@router.post(
    "/purchase",
    response_model=CreateExtendedClassesPackPurchaseLinkResponse,
    responses={
        "409": {
            "model": StandardErrorResponse[ERROR_409_TYPES],
            "description": "The user already owns the extended classes pack.",
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def create_purchase_link(
    args: CreateExtendedClassesPackPurchaseLinkRequest,
    authorization: Optional[str] = Header(None),
):
    """Creates the purchase link to buy the extended classes pack.

    Requires standard authorization.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        entitlement = await get_entitlement(
            itgs,
            user_sub=auth_result.result.sub,
            identifier="extended-classes-pack-06272023",
        )
        if entitlement is None:
            return PROVIDER_ERROR_RESPONSE

        if entitlement.is_active:
            return ALREADY_OWNED_RESPONSE

        try:
            customer_id = await ensure_stripe_customer(itgs, auth_result)
        except UserSafeError as exc:
            return exc.response

        uid = f"oseh_oscs_{secrets.token_urlsafe(16)}"
        is_dev = os.environ["ENVIRONMENT"] == "dev"
        try:
            session = await run_in_threadpool(
                stripe.checkout.Session.create,
                api_key=os.environ["OSEH_STRIPE_SECRET_KEY"],
                customer=customer_id,
                success_url=(
                    os.environ["ROOT_FRONTEND_URL"]
                    + args.success_path
                    + "?slug=extended-classes-pack-06272023&session={CHECKOUT_SESSION_ID}"
                ),
                cancel_url=os.environ["ROOT_FRONTEND_URL"] + args.cancel_path,
                mode="payment",
                line_items=[
                    {
                        "price": (
                            "price_1NNd6AEYCG5oJAnI1LZlsUPs"
                            if not is_dev
                            else "price_1NNd6nEYCG5oJAnION7dBnik"
                        ),
                        "quantity": 1,
                    }
                ],
            )
            assert session.url is not None
        except Exception as exc:
            await handle_error(exc)
            raise UserSafeError(
                f"Failed to create checkout session for {auth_result.result.sub=}",
                Response(
                    content=StandardErrorResponse[ERROR_503_TYPES](
                        type="provider_error",
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

            return CreateExtendedClassesPackPurchaseLinkResponse(url=session.url)
        except UserSafeError as exc:
            await cancel_session()
            return exc.response
        except Exception:
            await cancel_session()
            raise
