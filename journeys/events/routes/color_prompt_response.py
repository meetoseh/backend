from typing import Literal, Optional
from fastapi import APIRouter, Header
from fastapi import Response
from pydantic import BaseModel, Field
from journeys.events.models import (
    CreateJourneyEventRequest,
    CreateJourneyEventResponse,
    CREATE_JOURNEY_EVENT_STANDARD_ERRORS_BY_CODE,
    CREATE_JOURNEY_EVENT_409_TYPES,
)
import journeys.events.helper as evhelper
from itgs import Itgs
from models import StandardErrorResponse
from pypika import Query, Table, Parameter
from pypika.terms import ExistsCriterion
from pypika.functions import Function


class ColorPromptData(BaseModel):
    index: int = Field(description="The index of the color the user selected.", ge=0)


EventTypeT = Literal["color_prompt_response"]
EventRequestDataT = ColorPromptData
EventResponseDataT = ColorPromptData

router = APIRouter()


@router.post(
    "/respond_color_prompt",
    response_model=CreateJourneyEventResponse[EventTypeT, EventResponseDataT],
    responses=CREATE_JOURNEY_EVENT_STANDARD_ERRORS_BY_CODE,
)
async def respond_to_journey_color_prompt(
    args: CreateJourneyEventRequest[EventRequestDataT],
    authorization: Optional[str] = Header(None),
):
    """Provides the given color response to the journey. Multiple color
    responses can be provided within a single session, but only if the
    journey has a color prompt.
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
        journeys = Table("journeys")

        result = await evhelper.create_journey_event(
            itgs,
            journey_uid=auth_result.result.journey_uid,
            user_sub=auth_result.result.user_sub,
            session_uid=args.session_uid,
            event_type="color_prompt_response",
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
                            == "color"
                        )
                        .where(
                            Function("json_array_length", journeys.prompt, "$.colors")
                            > Parameter("?")
                        )
                    ),
                    [args.data.index],
                )
            ],
            bonus_error_checks=[
                (
                    ExistsCriterion(
                        Query.from_(journeys)
                        .select(1)
                        .where(journeys.uid == Parameter("?"))
                        .where(
                            Function("json_extract", journeys.prompt, "$.style")
                            == "color"
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
                                message=(
                                    "A color prompt response can only be provided to a "
                                    "color prompt journey."
                                ),
                            ).json(),
                            headers={
                                "Content-Type": "application/json; charset=utf-8",
                            },
                            status_code=409,
                        ),
                    ),
                ),
                (
                    ExistsCriterion(
                        Query.from_(journeys)
                        .select(1)
                        .where(journeys.uid == Parameter("?"))
                        .where(
                            Function("json_array_length", journeys.prompt, "$.colors")
                            > Parameter("?")
                        )
                    ),
                    [args.journey_uid, args.data.index],
                    lambda: evhelper.CreateJourneyEventResult(
                        result=None,
                        error_type="impossible_event_data",
                        error_response=Response(
                            content=StandardErrorResponse[
                                CREATE_JOURNEY_EVENT_409_TYPES
                            ](
                                type="impossible_event_data",
                                message=(
                                    "The given index is outside of the range of the "
                                    "journey's color prompt."
                                ),
                            ).json(),
                            headers={
                                "Content-Type": "application/json; charset=utf-8",
                            },
                            status_code=409,
                        ),
                    ),
                ),
            ],
            prefix_sum_updates=[
                evhelper.PrefixSumUpdate(
                    category='color_active',
                    amount=1,
                    simple=True,
                    category_value=args.data.index,
                    event_type=None,
                    event_data_field=None
                ),
                evhelper.PrefixSumUpdate(
                    category='color_active',
                    amount=-1,
                    simple=False,
                    category_value=None,
                    event_type='color_prompt_response',
                    event_data_field='index'
                )
            ]
        )
        if not result.success:
            return result.error_response
        return result.result.response
