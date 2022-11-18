from typing import Literal, Optional
from fastapi import APIRouter, Header
from fastapi import Response
from journeys.events.models import (
    CreateJourneyEventRequest,
    CreateJourneyEventResponse,
    NoJourneyEventData,
    CREATE_JOURNEY_EVENT_STANDARD_ERRORS_BY_CODE,
    ERROR_JOURNEY_NOT_FOUND_RESPONSE,
    CREATE_JOURNEY_EVENT_409_TYPES,
)
import journeys.events.helper
from itgs import Itgs
from models import StandardErrorResponse


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
        auth_result = await journeys.events.helper.auth_create_journey_event(
            itgs,
            authorization=authorization,
            journey_jwt=args.journey_jwt,
            journey_uid=args.journey_uid,
        )
        if not auth_result.success:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor("weak")
        response = await cursor.execute(
            """
            SELECT
                EXISTS (
                    SELECT 1 FROM journeys
                    WHERE uid=? AND json_extract(journeys.prompt, '$.style') = ?
                ) AS b1,
                EXISTS (
                    SELECT 1 FROM journey_events
                    WHERE
                        EXISTS (
                            SELECT 1 FROM journey_sessions
                            WHERE journey_sessions.id = journey_events.journey_session_id
                              AND journey_sessions.uid = ?
                              AND EXISTS (
                                SELECT 1 FROM users
                                WHERE journey_sessions.user_id = users.id
                                  AND users.sub = ?
                              )
                        )
                        AND journey_events.evtype = ?
                        AND NOT EXISTS (
                            SELECT 1 FROM journey_events AS je
                            WHERE je.journey_session_id = journey_events.journey_session_id
                              AND je.evtype = ?
                              AND je.journey_time > journey_events.journey_time
                        )
                ) AS b2
            """,
            (
                auth_result.result.journey_uid,
                "press",
                args.session_uid,
                auth_result.result.user_sub,
                "press_prompt_start_response",
                "press_prompt_end_response",
            ),
        )
        if not response.results:
            return ERROR_JOURNEY_NOT_FOUND_RESPONSE

        is_correct_prompt: bool = bool(response.results[0][0])
        is_already_pressing: bool = bool(response.results[0][1])

        if not is_correct_prompt:
            return Response(
                content=StandardErrorResponse[CREATE_JOURNEY_EVENT_409_TYPES](
                    type="impossible_event",
                    message=(
                        "A press prompt start response can only be sent for a journey "
                        "that has a press prompt."
                    ),
                ).json(),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                },
                status_code=409,
            )

        if not is_already_pressing:
            return Response(
                content=StandardErrorResponse[CREATE_JOURNEY_EVENT_409_TYPES](
                    type="impossible_event_data",
                    message=(
                        "A press prompt end response can only be sent if the user "
                        "is already pressing down on the press prompt."
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
            event_type="press_prompt_end_response",
            event_data=args.data,
            journey_time=args.journey_time,
        )
        if not result.success:
            return result.error_response
        return result.result.response
