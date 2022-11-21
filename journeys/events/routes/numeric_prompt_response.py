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


class NumericPromptData(BaseModel):
    rating: int = Field(title="Rating", description="The rating given by the user.")


EventTypeT = Literal["numeric_prompt_response"]
EventRequestDataT = NumericPromptData
EventResponseDataT = NumericPromptData

router = APIRouter()


@router.post(
    "/respond_numeric_prompt",
    response_model=CreateJourneyEventResponse[EventTypeT, EventResponseDataT],
    responses=CREATE_JOURNEY_EVENT_STANDARD_ERRORS_BY_CODE,
)
async def respond_to_journey_numeric_prompt(
    args: CreateJourneyEventRequest[EventRequestDataT],
    authorization: Optional[str] = Header(None),
):
    """Provides the given numeric response to the journey. Multiple numeric
    responses can be provided within a single session, but only if the
    journey has a numeric prompt.
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
            event_type="numeric_prompt_response",
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
                            == "numeric"
                        )
                        .where(
                            Function("json_extract", journeys.prompt, "$.min")
                            <= Parameter("?")
                        )
                        .where(
                            Function("json_extract", journeys.prompt, "$.max")
                            >= Parameter("?")
                        )
                    ),
                    [args.data.rating, args.data.rating],
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
                            == "numeric"
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
                                    "A numeric prompt response can only be provided to a "
                                    "numeric prompt journey."
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
                            Function("json_extract", journeys.prompt, "$.min")
                            <= Parameter("?")
                        )
                        .where(
                            Function("json_extract", journeys.prompt, "$.max")
                            >= Parameter("?")
                        )
                    ),
                    [args.journey_uid, args.data.rating, args.data.rating],
                    lambda: evhelper.CreateJourneyEventResult(
                        result=None,
                        error_type="impossible_event_data",
                        error_response=Response(
                            content=StandardErrorResponse[
                                CREATE_JOURNEY_EVENT_409_TYPES
                            ](
                                type="impossible_event_data",
                                message=(
                                    "The given rating is outside of the range of the "
                                    "journey's numeric prompt."
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
        )
        if not result.success:
            return result.error_response
        return result.result.response
