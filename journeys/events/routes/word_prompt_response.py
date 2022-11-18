from typing import Literal, Optional
from fastapi import APIRouter, Header
from fastapi import Response
from pydantic import BaseModel, Field
from journeys.events.models import (
    CreateJourneyEventRequest,
    CreateJourneyEventResponse,
    CREATE_JOURNEY_EVENT_STANDARD_ERRORS_BY_CODE,
    ERROR_JOURNEY_NOT_FOUND_RESPONSE,
    CREATE_JOURNEY_EVENT_409_TYPES,
)
import journeys.events.helper
from itgs import Itgs
from models import StandardErrorResponse
import json


class WordPromptData(BaseModel):
    index: int = Field(description="The index of the word the user selected.", ge=0)


EventTypeT = Literal["word_prompt_response"]
EventRequestDataT = WordPromptData
EventResponseDataT = WordPromptData

router = APIRouter()


@router.post(
    "/respond_word_prompt",
    response_model=CreateJourneyEventResponse[EventTypeT, EventResponseDataT],
    responses=CREATE_JOURNEY_EVENT_STANDARD_ERRORS_BY_CODE,
)
async def respond_to_journey_word_prompt(
    args: CreateJourneyEventRequest[EventRequestDataT],
    authorization: Optional[str] = Header(None),
):
    """Provides the given word response to the journey. Multiple word
    responses can be provided within a single session, but only if the
    journey has a word prompt.
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

        conn = await itgs.conn()
        cursor = conn.cursor("none")
        response = await cursor.execute(
            "SELECT prompt FROM journeys WHERE uid=?",
            (auth_result.result.journey_uid,),
        )
        if not response.results:
            return ERROR_JOURNEY_NOT_FOUND_RESPONSE

        prompt_raw: str = response.results[0][0]
        prompt: dict = json.loads(prompt_raw)

        if prompt["style"] != "word":
            return Response(
                content=StandardErrorResponse[CREATE_JOURNEY_EVENT_409_TYPES](
                    type="impossible_event",
                    message=(
                        "A word prompt response can only be provided to a "
                        "word prompt journey, but this journey has a "
                        f"{prompt['style']} prompt."
                    ),
                ).json(),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                },
                status_code=409,
            )

        if args.data.index >= len(prompt["options"]):
            return Response(
                content=StandardErrorResponse[CREATE_JOURNEY_EVENT_409_TYPES](
                    type="impossible_event_data",
                    message=(
                        "The given index is outside of the range of the "
                        "journey's word prompt."
                    ),
                ).json(),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                },
                status_code=409,
            )

        result = await journeys.events.helper.create_journey_event(
            itgs,
            journey_uid=auth_result.result.journey_uid,
            user_sub=auth_result.result.user_sub,
            session_uid=args.session_uid,
            event_type="word_prompt_response",
            event_data=args.data,
            journey_time=args.journey_time,
        )
        if not result.success:
            return result.error_response
        return result.result.response
