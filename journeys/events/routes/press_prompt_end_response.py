from typing import Literal, Optional
from fastapi import APIRouter, Header
from fastapi import Response
from journeys.events.models import (
    CreateJourneyEventRequest,
    CreateJourneyEventResponse,
    NoJourneyEventData,
    CREATE_JOURNEY_EVENT_STANDARD_ERRORS_BY_CODE,
    CREATE_JOURNEY_EVENT_409_TYPES,
)
import journeys.events.helper as evhelper
from itgs import Itgs
from models import StandardErrorResponse
from pypika import Query, Table, Parameter
from pypika.terms import ExistsCriterion
from pypika.functions import Function


EventTypeT = Literal["press_prompt_end_response"]
EventRequestDataT = NoJourneyEventData
EventResponseDataT = NoJourneyEventData

router = APIRouter()


@router.post(
    "/respond_press_prompt/end",
    response_model=CreateJourneyEventResponse[EventTypeT, EventResponseDataT],
    responses=CREATE_JOURNEY_EVENT_STANDARD_ERRORS_BY_CODE,
)
async def respond_to_journey_press_prompt_end(
    args: CreateJourneyEventRequest[EventRequestDataT],
    authorization: Optional[str] = Header(None),
):
    """Indicates the user stopped pressing down on a journey press prompt, but
    only if the journey has a press prompt and the user is already pressing
    down on the press prompt.
    """
    async with Itgs() as itgs:
        auth_result = await evhelper.auth_create_journey_event(
            itgs,
            authorization=authorization,
            journey_jwt=args.journey_jwt,
            journey_uid=args.journey_uid,
        )
        if not auth_result.success:
            return auth_result.error_response

        journey_sessions = Table("journey_sessions")
        journey_events = Table("journey_events").as_("je")
        journey_events_2 = Table("journey_events").as_("je2")
        journeys = Table("journeys")

        result = await evhelper.create_journey_event(
            itgs,
            journey_uid=auth_result.result.journey_uid,
            user_sub=auth_result.result.user_sub,
            session_uid=args.session_uid,
            event_type="press_prompt_end_response",
            event_data=args.data,
            journey_time=args.journey_time,
            bonus_terms=[
                (
                    ExistsCriterion(
                        Query.from_(journeys)
                        .select(1)
                        .where(journeys.id == journey_sessions.journey_id)
                        .where(
                            Function("json_extract", journeys.prompt, "$.style")
                            == "press"
                        )
                    ),
                    [],
                ),
                (
                    ExistsCriterion(
                        Query.from_(journey_events)
                        .select(1)
                        .where(journey_events.journey_session_id == journey_sessions.id)
                        .where(journey_events.evtype == "press_prompt_start_response")
                        .where(
                            ~ExistsCriterion(
                                Query.from_(journey_events_2)
                                .select(1)
                                .where(
                                    journey_events_2.journey_session_id
                                    == journey_sessions.id
                                )
                                .where(
                                    journey_events_2.journey_time
                                    > journey_events.journey_time
                                )
                                .where(
                                    journey_events_2.evtype
                                    == "press_prompt_end_response"
                                )
                            )
                        )
                    ),
                    [],
                ),
            ],
            bonus_error_checks=[
                (
                    ExistsCriterion(
                        Query.from_(journeys)
                        .select(1)
                        .where(journeys.uid == Parameter("?"))
                        .where(
                            Function("json_extract", journeys.prompt, "$.style")
                            == "press"
                        )
                    ),
                    [args.journey_uid],
                    lambda: evhelper.CreateJourneyEventResult(
                        result=None,
                        error_type="impossible_event",
                        error_response=Response(
                            content=StandardErrorResponse[
                                CREATE_JOURNEY_EVENT_409_TYPES
                            ](
                                type="impossible_event",
                                message="A press prompt start event requires the journey has a press prompt",
                            ).json(),
                            headers={"Content-Type": "application/json; charset=utf-8"},
                            status_code=409,
                        ),
                    ),
                ),
                (
                    ExistsCriterion(
                        Query.from_(journey_events)
                        .select(1)
                        .where(
                            ExistsCriterion(
                                Query.from_(journey_sessions)
                                .select(1)
                                .where(journey_sessions.uid == Parameter("?"))
                                .where(
                                    journey_sessions.id
                                    == journey_events.journey_session_id
                                )
                            )
                        )
                        .where(journey_events.evtype == "press_prompt_start_response")
                        .where(
                            ~ExistsCriterion(
                                Query.from_(journey_events_2)
                                .select(1)
                                .where(
                                    journey_events_2.journey_session_id
                                    == journey_sessions.id
                                )
                                .where(
                                    journey_events_2.journey_time
                                    > journey_events.journey_time
                                )
                                .where(
                                    journey_events_2.evtype
                                    == "press_prompt_end_response"
                                )
                            )
                        )
                    ),
                    [args.session_uid],
                    lambda: evhelper.CreateJourneyEventResult(
                        result=None,
                        error_type="impossible_event_data",
                        error_response=Response(
                            content=StandardErrorResponse[
                                CREATE_JOURNEY_EVENT_409_TYPES
                            ](
                                type="impossible_event_data",
                                message=(
                                    "The user is not pressing down on the press prompt."
                                ),
                            ).json(),
                            headers={"Content-Type": "application/json; charset=UTF-8"},
                            status_code=409,
                        ),
                    ),
                ),
            ],
            prefix_sum_updates=[
                evhelper.PrefixSumUpdate(
                    category="press_active",
                    amount=-1,
                    simple=True,
                    category_value=None,
                    event_type=None,
                    event_data_field=None,
                )
            ],
        )
        if not result.success:
            return result.error_response
        return result.result.response
