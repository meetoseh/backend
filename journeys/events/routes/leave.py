from typing import Literal, Optional
from fastapi import APIRouter, Header
from journeys.events.models import (
    CreateJourneyEventRequest,
    CreateJourneyEventResponse,
    NameEventData,
    NoJourneyEventData,
    CREATE_JOURNEY_EVENT_STANDARD_ERRORS_BY_CODE,
)
import journeys.events.helper
from itgs import Itgs

EventTypeT = Literal["leave"]
EventRequestDataT = NoJourneyEventData
EventResponseDataT = NameEventData

router = APIRouter()


@router.post(
    "/leave",
    response_model=CreateJourneyEventResponse[EventTypeT, EventResponseDataT],
    responses=CREATE_JOURNEY_EVENT_STANDARD_ERRORS_BY_CODE,
)
async def leave_journey(
    args: CreateJourneyEventRequest[EventRequestDataT],
    authorization: Optional[str] = Header(None),
):
    """Marks that the given user left the given journey. A user can leave a
    session only once, after only after joining.
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

        display_name = await journeys.events.helper.get_display_name(
            itgs, auth_result.result
        )

        result = await journeys.events.helper.create_journey_event(
            itgs,
            journey_uid=auth_result.result.journey_uid,
            user_sub=auth_result.result.user_sub,
            session_uid=args.session_uid,
            event_type="leave",
            event_data=NameEventData(name=display_name),
            journey_time=args.journey_time,
            prefix_sum_updates=[
                journeys.events.helper.PrefixSumUpdate(
                    category="users",
                    amount=-1,
                    simple=True,
                    category_value=None,
                    event_type=None,
                    event_data_field=None,
                )
            ],
            store_event_data=NoJourneyEventData(),
        )
        if not result.success:
            return result.error_response
        return result.result.response
