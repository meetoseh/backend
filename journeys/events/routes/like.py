from typing import Literal, Optional
from fastapi import APIRouter, Header
from journeys.events.models import (
    CreateJourneyEventRequest,
    CreateJourneyEventResponse,
    NoJourneyEventData,
    CREATE_JOURNEY_EVENT_STANDARD_ERRORS_BY_CODE,
)
import journeys.events.helper
from itgs import Itgs

EventTypeT = Literal["like"]
EventRequestDataT = NoJourneyEventData
EventResponseDataT = NoJourneyEventData

router = APIRouter()


@router.post(
    "/like",
    response_model=CreateJourneyEventResponse[EventTypeT, EventResponseDataT],
    responses=CREATE_JOURNEY_EVENT_STANDARD_ERRORS_BY_CODE,
)
async def like_journey(
    args: CreateJourneyEventRequest[EventRequestDataT],
    authorization: Optional[str] = Header(None),
):
    """Marks that the given user tapped the like button for the given journey.
    A user can tap the like button multiple times to produce independent like events.
    """
    async with Itgs() as itgs:
        auth_result = await journeys.events.helper.auth_create_journey_event(
            itgs,
            authorization=authorization,
            journey_jwt=args.journey_jwt,
            journey_uid=args.journey_uid,
        )
        if not auth_result.success:
            return auth_result.error_response

        result = await journeys.events.helper.create_journey_event(
            itgs,
            journey_uid=auth_result.result.journey_uid,
            user_sub=auth_result.result.user_sub,
            session_uid=args.session_uid,
            event_type="like",
            event_data=args.data,
            journey_time=args.journey_time,
        )
        if not result.success:
            return result.error_response
        return result.result.response
