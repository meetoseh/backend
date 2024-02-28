from fastapi import APIRouter, Header
from fastapi.responses import Response
from typing import Annotated, Literal, Optional
from revenue_cat import OfferingsWithoutMetadata
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from auth import auth_any
from itgs import Itgs
import users.lib.entitlements as entitlements
import users.lib.offerings as offerings

router = APIRouter()


ERROR_404_TYPES = Literal["no_offerings"]
ERROR_NO_OFFERINGS_RESPONSE = Response(
    status_code=404,
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="no_offerings",
        message=(
            "The user cannot subscribe on this platform at this time, "
            "possibly because of a pending or failed transaction"
        ),
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
)
ERROR_409_TYPES = Literal["already_subscribed"]
ERROR_ALREADY_SUBSCRIBED_RESPONSE = Response(
    status_code=409,
    content=StandardErrorResponse[ERROR_409_TYPES](
        type="already_subscribed", message="The user is already entitled to Oseh+"
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
)


@router.get(
    "/offerings",
    response_model=OfferingsWithoutMetadata,
    responses={
        "404": {
            "description": "The user cannot subscribe on this platform at this time, possibly because of a pending or failed transaction",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        "409": {
            "description": "The user is already entitled to Oseh+",
            "model": StandardErrorResponse[ERROR_409_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def read_offerings(
    platform: Literal["stripe"],
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Determines what RevenueCat offerings are available to the user. This is
    preferred over accessing them directly via RevenueCat as it will manage
    users with multiple revenue cat ids automatically as well as ensuring the
    offerings are actually available in this environment.

    Requires standard authorization.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        entitlement = await entitlements.get_entitlement(
            itgs, user_sub=auth_result.result.sub, identifier="pro", force=False
        )
        if entitlement is not None and entitlement.is_active:
            return ERROR_ALREADY_SUBSCRIBED_RESPONSE

        offers = await offerings.get_offerings(
            itgs, user_sub=auth_result.result.sub, platform=platform, force=False
        )
        if offers is None:
            return ERROR_NO_OFFERINGS_RESPONSE

        abridged_offers = OfferingsWithoutMetadata(
            current_offering_id=offers.current_offering_id,
            offerings=[
                o
                for o in offers.offerings
                if o.identifier == offers.current_offering_id
            ],
        )
        return Response(
            content=abridged_offers.__pydantic_serializer__.to_json(abridged_offers),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=200,
        )
