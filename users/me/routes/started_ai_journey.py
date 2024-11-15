import secrets
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Optional
from error_middleware import handle_contextless_error
from models import STANDARD_ERRORS_BY_CODE
from auth import auth_any
from journeys.auth import auth_any as auth_journey_any
from itgs import Itgs
from journeys.lib.notifs import on_entering_lobby
from users.lib.timezones import get_user_timezone
import unix_dates

router = APIRouter()


class StartedAIJourneyRequest(BaseModel):
    journey_jwt: str = Field(
        description="The JWT for the journey, which shows that the user is authorized to start it"
    )


@router.post(
    "/started_ai_journey",
    status_code=204,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def started_ai_journey(
    args: StartedAIJourneyRequest,
    authorization: Optional[str] = Header(None),
):
    """Tracks that the user has decided to actually start the given ai journey.
    This ensures that the users history is accurate, and they won't be
    personalized towards content they haven't actually seen.

    Requires standard authorization.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        journey_auth_result = await auth_journey_any(itgs, f"bearer {args.journey_jwt}")
        if journey_auth_result.result is None:
            return journey_auth_result.error_response

        await on_entering_lobby(
            itgs,
            user_sub=auth_result.result.sub,
            journey_uid=journey_auth_result.result.journey_uid,
            action=f"entering an ai journey lobby",
        )

        conn = await itgs.conn()
        cursor = conn.cursor("none")
        user_journey_uid = f"oseh_uj_{secrets.token_urlsafe(16)}"
        user_tz = await get_user_timezone(itgs, user_sub=auth_result.result.sub)
        created_at = time.time()
        created_at_unix_date = unix_dates.unix_timestamp_to_unix_date(
            created_at, tz=user_tz
        )
        response = await cursor.execute(
            """
            INSERT INTO user_journeys (
                uid, user_id, journey_id, created_at, created_at_unix_date
            )
            SELECT
                ?, users.id, journeys.id, ?, ?
            FROM users, journeys
            WHERE
                users.sub = ?
                AND journeys.uid = ?
            """,
            (
                user_journey_uid,
                created_at,
                created_at_unix_date,
                auth_result.result.sub,
                journey_auth_result.result.journey_uid,
            ),
        )
        if response.rows_affected is None or response.rows_affected < 1:
            await handle_contextless_error(
                extra_info=f"failed to store ai journey user_journey row: {auth_result.result.sub=}, {journey_auth_result.result.journey_uid=}"
            )

        return Response(status_code=204)
