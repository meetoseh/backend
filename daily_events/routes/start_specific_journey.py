from typing import Literal, Optional
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from daily_events.models.external_daily_event import ExternalDailyEvent
from journeys.models.external_journey import ExternalJourney
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from response_utils import response_to_bytes, cleanup_response
import auth
import daily_events.auth
import journeys.auth
import daily_events.lib.read_one_external
import journeys.lib.read_one_external
from itgs import Itgs
import secrets


router = APIRouter()


class StartSpecificJourneyRequest(BaseModel):
    daily_event_uid: str = Field(
        description=(
            "The UID of the daily event within which you are starting a journey. "
            "This must match the sub of the daily event JWT."
        )
    )

    daily_event_jwt: str = Field(
        description=(
            "The JWT which provides access to the daily event. Must have the "
            "start_full access level. The JWT is revoked after a successful call."
        )
    )

    journey_uid: str = Field(
        description=("The UID of the journey within the dialy event to start.")
    )


ERROR_404_TYPES = Literal["not_found"]
NOT_FOUND = Response(
    status_code=404,
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="not_found",
        message=(
            "Although the JWT you provided is valid, no such daily event exists; "
            "this is either a server error, the daily event has been deleted, "
            "or that journey is not part of that daily event"
        ),
    ).json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
)


@router.post(
    "/start_specific",
    status_code=201,
    response_model=ExternalJourney,
    responses={
        "404": {
            "description": "Despite a valid JWT, the daily event does not exist. It may have been deleted.",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def start_specific_journey(
    args: StartSpecificJourneyRequest, authorization: Optional[str] = Header(None)
):
    """Starts a specific journey within a daily event. This requires the
    `start_full` access level within the JWT (the `oseh:level` claim). This
    begins a new session within the journey, which should be used to post events
    (at minimum the join and leave events). The returned JWT can also be used
    for connecting to the live stream of temporally adjacent events, the
    standard HTTP endpoint for historical events, the profile pictures endpoint
    to sample users in the journey across time, and the standard HTTP endpoint
    for journey statistics across time.

    The daily event JWT is revoked after a successful call, as it is preferred
    that the client use the daily event read endpoint (now, which returns a
    JWT) to determine access levels, rather than using the JWT claims combined
    with state.

    This also requires standard authorization, which is used to determine which
    user to associate with the session.
    """
    async with Itgs() as itgs:
        std_auth_result = await auth.auth_any(itgs, authorization)
        if not std_auth_result.success:
            return std_auth_result.error_response

        de_auth_result = await daily_events.auth.auth_any(
            itgs, f"bearer {args.daily_event_jwt}"
        )
        if not de_auth_result.success:
            return de_auth_result.error_response

        if de_auth_result.result.daily_event_uid != args.daily_event_uid:
            return auth.AUTHORIZATION_UNKNOWN_TOKEN

        if "start_full" not in de_auth_result.result.level:
            return auth.AUTHORIZATION_UNKNOWN_TOKEN

        daily_event_raw = await daily_events.lib.read_one_external.read_one_external(
            itgs, uid=args.daily_event_uid, level=de_auth_result.result.level
        )

        if daily_event_raw is None:
            return NOT_FOUND

        daily_event_bytes = await response_to_bytes(daily_event_raw)
        daily_event = ExternalDailyEvent.parse_raw(
            daily_event_bytes, content_type="application/json"
        )

        if not any(journey.uid == args.journey_uid for journey in daily_event.journeys):
            return NOT_FOUND

        jwt = await journeys.auth.create_jwt(itgs, journey_uid=args.journey_uid)
        journey_response = await journeys.lib.read_one_external.read_one_external(
            itgs, journey_uid=args.journey_uid, jwt=jwt
        )
        if journey_response is None:
            return NOT_FOUND

        return journey_response
