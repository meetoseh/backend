import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal, Optional
from auth import auth_any
from error_middleware import handle_warning
from itgs import Itgs
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
import users.lib.entitlements as entitlements


class ReadEntitlementResponse(BaseModel):
    identifier: str = Field(
        description=("The identifier of the requested entitlement.")
    )
    is_active: bool = Field(description=("Whether the user has the given entitlement"))
    active_info: Optional[entitlements.CachedEntitlementActiveInfo] = Field(
        None,
        description=(
            "If the user has this entitlement, information about the "
            "subscription they have for information purposes only. This "
            "is not intended to be used for determining if the use has the "
            "entitlement, as we do not directly manage subscriptions. For "
            "stripe, for example, the customer portal shows authoritative "
            "info. For ios, the App Store. For google, Google Play."
        ),
    )
    expiration_date: Optional[float] = Field(
        description=(
            "If the entitlement will expire unless renewed, this is the "
            "earliest time in seconds since the epoch at which it will "
            "expire. This value may be in the past, but should never be "
            "used to determine whether the entitlement is active - it is "
            "only provided for informational purposes."
        )
    )
    checked_at: float = Field(
        description=(
            "The time that the entitlement was retrieved from the source of truth."
        )
    )


router = APIRouter()


ERROR_429_TYPES = Literal["ratelimited"]
ERROR_503_TYPES = Literal["not_found"]


@router.get(
    "/entitlements/{identifier}",
    response_model=ReadEntitlementResponse,
    responses={
        "429": {
            "model": StandardErrorResponse[ERROR_429_TYPES],
            "description": "The user has exceeded the rate limit for this endpoint.",
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def read_entitlement(
    identifier: str,
    authorization: Optional[str] = Header(None),
    pragma: Optional[str] = Header(None),
):
    """A convenience endpoint to fetch the entitlement information on the
    authorized user for a given entitlement, without needing to fetch the
    revenue cat id. Since all the server endpoints will verify entitlement
    information, this is primarily used for display logic: i.e., rather than
    showing a button which when clicked will fail because the user is not
    entitled, the button can be hidden.

    The result is cached server-side. The server cache can be skipped using the
    `Pragma: no-cache` header. Requests with this header may be ratelimited.

    Since this is not critical functionality, it can be appropriate to cache the
    response for a somewhat long duration, so long as the user has the ability
    to "flush" the cache, i.e., by refreshing the cache whenever the app is
    launched fresh (or anything that would effect entitlement information that
    the client knows about, such as the user subscribing via the client). If
    this is done "blind", e.g., the fresh app launch example, the 429 response
    can be handled by retrying with caching enabled (i.e., no pragma header)

    This requires standard authentication.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        if identifier != "pro":
            await handle_warning(
                f"{__name__}:unknown_identifier",
                f"unknown identifier {identifier} requested by {auth_result.result.sub}",
            )
            return Response(
                content=ReadEntitlementResponse(
                    identifier=identifier,
                    is_active=False,
                    active_info=None,
                    expiration_date=None,
                    checked_at=time.time(),
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        force = pragma == "no-cache"
        if force:
            redis = await itgs.redis()
            key = f"entitlements:read:force:ratelimit:{auth_result.result.sub}"
            success = await redis.set(key, "1", ex=30, nx=True)
            if not success:
                return Response(
                    content=StandardErrorResponse[ERROR_429_TYPES](
                        type="ratelimited",
                        message="You have exceeded the rate limit for this endpoint.",
                    ).model_dump_json(),
                    headers={"Content-Type": "application/json; charset=utf-8"},
                    status_code=429,
                )

        result = await entitlements.get_entitlement(
            itgs,
            user_sub=auth_result.result.sub,
            identifier=identifier,
            force=force,
        )
        if result is None:
            return Response(
                content=StandardErrorResponse[ERROR_503_TYPES](
                    type="not_found",
                    message="Although your authorization is valid, you don't seem to exist.",
                ).model_dump_json(),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Retry-After": "10",
                },
                status_code=503,
            )

        return Response(
            content=ReadEntitlementResponse(
                identifier=identifier,
                is_active=result.is_active,
                active_info=result.active_info,
                expiration_date=result.expires_at,
                checked_at=result.checked_at,
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
