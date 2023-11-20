import secrets
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Optional
from error_middleware import handle_contextless_error
from models import STANDARD_ERRORS_BY_CODE, AUTHORIZATION_UNKNOWN_TOKEN
from auth import auth_any
from itgs import Itgs
import journeys.auth
from journeys.lib.notifs import on_entering_lobby

router = APIRouter()


class StartedExtendedClassesPackJourney(BaseModel):
    journey_uid: str = Field(description="The uid of the journey that was started")
    journey_jwt: str = Field(
        description="The jwt that shows you have access to the journey"
    )


@router.post(
    "/started",
    status_code=204,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def started_related_journey(
    args: StartedExtendedClassesPackJourney,
    authorization: Optional[str] = Header(None),
):
    """Tracks that the user has decided to actually start the journey
    returned from /consider, which adds it to their history (and thus
    giving them access to it in the future)

    Requires standard authorization
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        journey_auth_result = await journeys.auth.auth_any(
            itgs, "bearer " + args.journey_jwt
        )
        if journey_auth_result.result is None:
            return journey_auth_result.error_response

        if journey_auth_result.result.journey_uid != args.journey_uid:
            return AUTHORIZATION_UNKNOWN_TOKEN

        conn = await itgs.conn()
        cursor = conn.cursor("none")

        user_journey_uid = f"oseh_uj_{secrets.token_urlsafe(16)}"
        new_last_taken_at = time.time()
        response = await cursor.execute(
            """
            INSERT INTO user_journeys (
                uid, user_id, journey_id, created_at
            )
            SELECT
                ?, users.id, journeys.id, ?
            FROM users, journeys
            WHERE
                users.sub = ?
                AND journeys.uid = ?
            """,
            (
                user_journey_uid,
                new_last_taken_at,
                auth_result.result.sub,
                args.journey_uid,
            ),
        )
        if response.rows_affected is None or response.rows_affected < 1:
            await handle_contextless_error(
                extra_info=f"failed to store user={auth_result.result.sub} started journey={args.journey_uid} in user_journeys"
            )

        await on_entering_lobby(
            itgs,
            user_sub=auth_result.result.sub,
            journey_uid=args.journey_uid,
            action=f"entering a lobby for their sample in the extended classes pack",
        )

        return Response(status_code=204)
