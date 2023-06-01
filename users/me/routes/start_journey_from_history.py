import secrets
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal, Optional
from error_middleware import handle_contextless_error
from journeys.lib.notifs import on_entering_lobby
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from journeys.models.external_journey import ExternalJourney
from journeys.lib.read_one_external import read_one_external
from journeys.auth import create_jwt as create_journey_jwt
from auth import auth_any
from itgs import Itgs
import logging


class StartJourneyFromHistoryRequest(BaseModel):
    journey_uid: str = Field(
        description="The unique identifier for the journey to start"
    )


router = APIRouter()


ERROR_404_TYPES = Literal["journey_not_found"]
JOURNEY_NOT_FOUND_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="journey_not_found",
        message="There is no journey with that uid, or its been deleted, or the user hasn't taken it before",
    ).json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=404,
)

ERROR_503_TYPES = Literal["failed_to_fetch"]
RACED_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_503_TYPES](
        type="failed_to_fetch",
        message="A journey was selected, but it could not be retrieved",
    ).json(),
    headers={"Content-Type": "application/json; charset=utf-8", "Retry-After": "5"},
    status_code=503,
)


@router.post(
    "/start_journey_from_history",
    status_code=200,
    response_model=ExternalJourney,
    responses={
        "404": {
            "description": "There is no journey with that uid, or its been deleted, or the user hasn't taken it before",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def start_journey_from_history(
    args: StartJourneyFromHistoryRequest, authorization: Optional[str] = Header(None)
):
    """Provides full information on a journey the user has already taken. This
    will update the user's history to track they've also taken this journey
    just now as well.

    Requires standard authorization.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor("none")

        response = await cursor.execute(
            """
            SELECT
                EXISTS (
                    SELECT 1 FROM user_journeys, users, journeys
                    WHERE
                        user_journeys.user_id = users.id
                        AND user_journeys.journey_id = journeys.id
                        AND users.sub = ?
                        AND journeys.uid = ?
                        AND journeys.deleted_at IS NULL
                ) AS b1
            """,
            (auth_result.result.sub, args.journey_uid),
        )
        if not response.results[0][0]:
            return JOURNEY_NOT_FOUND_RESPONSE

        journey_jwt = await create_journey_jwt(itgs, journey_uid=args.journey_uid)
        journey = await read_one_external(
            itgs, journey_uid=args.journey_uid, jwt=journey_jwt
        )
        if journey is None:
            logging.error(f"Failed to fetch journey {args.journey_uid}")
            return RACED_RESPONSE

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
                f"oseh_uj_{secrets.token_urlsafe(16)}",
                time.time(),
                auth_result.result.sub,
                args.journey_uid,
            ),
        )
        if response.rows_affected is None or response.rows_affected < 1:
            await handle_contextless_error(
                f"failed to store user_journey for {auth_result.result.sub=} and {args.journey_uid=} from history"
            )

        await on_entering_lobby(
            itgs,
            auth_result.result.sub,
            args.journey_uid,
            "entering a lobby from their history",
        )

        return journey
