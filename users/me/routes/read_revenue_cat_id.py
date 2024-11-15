import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal, Optional
from auth import auth_any
from itgs import Itgs
import users.lib.revenue_cat

from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse


class ReadRevenueCatIdResponse(BaseModel):
    revenue_cat_id: str = Field(
        description=(
            "The RevenueCat ID that can be used to fetch entitlements "
            "when combined with the appropriate public key for your "
            "device. https://www.revenuecat.com/docs/customer-info. "
            "This value MUST be treated as a long-lived secret, meaning "
            "it should not be stored unencrypted."
        )
    )


router = APIRouter()


ERROR_503_TYPES = Literal["not_found"]


@router.get(
    "/revenue_cat_id",
    response_model=ReadRevenueCatIdResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_revenue_cat_id(authorization: Optional[str] = Header(None)):
    """Returns the unique revenue cat id for the authorized user. This
    value is not the same as the users sub and can be used, when combined
    with the appropriate public key for the platform, to fetch entitlements
    from revenue cat as described
    [here](https://www.revenuecat.com/docs/customer-info).

    This value MUST be treated as a long-lived secret, meaning it should not be
    stored unencrypted - for the web, this means it should not be stored. For
    mobile, it may be stored encrypted, such as via the secure enclave on ios.
    For both, no-cache headers are returned but they still need to avoid
    explicit response caching like the web
    [Cache](https://developer.mozilla.org/en-US/docs/Web/API/Cache) interface
    effecting this response.

    If you just need to know if the user has an active Pro subscription,
    and you don't otherwise need detailed entitlement information, prefer
    `GET /api/1/users/me/entitlements/pro`, which avoids even handling the
    revenue cat id.

    If the client is unable to connect to revenuecat, it must fallback to
    the read entitlements endpoint for determining the users current
    entitlements, even if some functionality is still not possible (i.e.,
    starting new subscriptions)

    A user MAY have multiple revenue cat ids associated with their account. This
    typically happens when the account was merged with another account. In this
    case, this endpoint returns only the most recently created revenue cat id,
    which may be missing entitlements. For this reason, the client should not
    rely on the revenue cat id for determining entitlements.

    This requires standard authentication.
    """
    request_at = time.time()
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        rc_id = await users.lib.revenue_cat.get_or_create_latest_revenue_cat_id(
            itgs, user_sub=auth_result.result.sub, now=request_at
        )
        if rc_id is None:
            return Response(
                content=StandardErrorResponse[ERROR_503_TYPES](
                    type="not_found",
                    message="despite valid authorization, the user was not found. it may have been deleted.",
                ).model_dump_json(),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Retry-After": "10",
                },
                status_code=503,
            )

        return Response(
            content=ReadRevenueCatIdResponse(revenue_cat_id=rc_id).model_dump_json(),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
                "Pragma": "no-cache",
                "Expires": "0",
            },
            status_code=200,
        )
