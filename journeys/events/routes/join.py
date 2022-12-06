import asyncio
from typing import Literal, Optional
from fastapi import APIRouter, Header
from fastapi.responses import Response
from journeys.events.models import (
    CreateJourneyEventRequest,
    CreateJourneyEventResponse,
    NoJourneyEventData,
    CREATE_JOURNEY_EVENT_STANDARD_ERRORS_BY_CODE,
    ERROR_JOURNEY_NOT_FOUND_RESPONSE,
)
import journeys.events.helper
from itgs import Itgs
from models import StandardErrorResponse
import users.lib.stats
import journeys.lib.stats

EventTypeT = Literal["join"]
EventRequestDataT = NoJourneyEventData
EventResponseDataT = NoJourneyEventData

router = APIRouter()


ERROR_503_TYPES = Literal["user_not_found"]


@router.post(
    "/join",
    response_model=CreateJourneyEventResponse[EventTypeT, EventResponseDataT],
    responses=CREATE_JOURNEY_EVENT_STANDARD_ERRORS_BY_CODE,
)
async def join_journey(
    args: CreateJourneyEventRequest[EventRequestDataT],
    authorization: Optional[str] = Header(None),
):
    """Marks that the given user joined the given journey. A user can join a
    journey multiple times, but only in separate sessions.
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

        # required for stats
        user_created_at, journey_subcategory = await asyncio.gather(
            get_user_created_at(itgs, sub=auth_result.result.sub),
            get_journey_subcategory(itgs, uid=args.journey_uid),
        )

        if user_created_at is None:
            return Response(
                content=StandardErrorResponse[ERROR_503_TYPES](
                    type="user_not_found",
                    message="Despite valid authorization, you don't seem to exist. Your account may have been deleted.",
                ).json(),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Retry-After": 15,
                },
                status_code=503,
            )

        if journey_subcategory is None:
            return ERROR_JOURNEY_NOT_FOUND_RESPONSE

        result = await journeys.events.helper.create_journey_event(
            itgs,
            journey_uid=auth_result.result.journey_uid,
            user_sub=auth_result.result.user_sub,
            session_uid=args.session_uid,
            event_type="join",
            event_data=args.data,
            journey_time=args.journey_time,
            prefix_sum_updates=[
                journeys.events.helper.PrefixSumUpdate(
                    category="users",
                    amount=1,
                    simple=True,
                    category_value=None,
                    event_type=None,
                    event_data_field=None,
                )
            ],
        )
        if not result.success:
            return result.error_response

        await users.lib.stats.on_journey_session_started(
            itgs,
            auth_result.result.user_sub,
            user_created_at=user_created_at,
            started_at=result.result.created_at,
        )
        await journeys.lib.stats.on_journey_session_started(
            itgs,
            subcategory=journey_subcategory,
            started_at=result.result.created_at,
            user_sub=auth_result.result.user_sub,
        )
        return result.result.response


async def get_user_created_at(itgs: Itgs, *, sub: str) -> Optional[float]:
    conn = await itgs.conn()
    cursor = conn.cursor('none')

    response = await cursor.execute(
        "SELECT created_at FROM users WHERE sub = ?",
        (sub,),
    )
    if not response.results:
        return None

    return response.results[0][0]


async def get_journey_subcategory(itgs: Itgs, *, uid: str) -> Optional[str]:
    conn = await itgs.conn()
    cursor = conn.cursor('none')

    response = await cursor.execute(
        """
        SELECT
            journey_subcategories.internal_name
        FROM journey_subcategories
        WHERE
            EXISTS (
                SELECT 1 FROM journeys
                WHERE journeys.journey_subcategory_id = journey_subcategories.id
                  AND journeys.uid = ?
            )
        """,
        (uid,),
    )
    if not response.results:
        return None

    return response.results[0][0]
