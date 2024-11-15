from fastapi import APIRouter, Header
from fastapi.responses import Response
from typing import Literal, Optional
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from journeys.models.external_journey import ExternalJourney
from journeys.lib.read_one_external import read_one_external
from journeys.auth import create_jwt as create_journey_jwt
from auth import auth_any
from itgs import Itgs
import logging


router = APIRouter()


ERROR_404_TYPES = Literal["none_found"]
NONE_FOUND_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="none_found",
        message="There were no ai journeys that the user hasn't already completed.",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=404,
)

ERROR_503_TYPES = Literal["failed_to_fetch"]
RACED_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_503_TYPES](
        type="failed_to_fetch",
        message="A journey was selected, but it could not be retrieved",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8", "Retry-After": "5"},
    status_code=503,
)


@router.post(
    "/start_ai_journey",
    status_code=200,
    response_model=ExternalJourney,
    responses={
        "404": {
            "description": "No ai journeys were found that the user hasn't already completed.",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def start_ai_journey(authorization: Optional[str] = Header(None)):
    """Fetches an AI journey that the user hasn't started yet, if there is one.

    Requires standard authorization.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor("none")

        response = await cursor.execute(
            """
            SELECT
                journeys.uid
            FROM journeys
            WHERE
                journeys.special_category = 'ai'
                AND journeys.deleted_at IS NULL
                AND NOT EXISTS (
                    SELECT 1 FROM course_journeys
                    WHERE course_journeys.journey_id = journeys.id
                )
                AND NOT EXISTS (
                    SELECT 1 FROM user_journeys, users
                    WHERE
                        user_journeys.user_id = users.id
                        AND user_journeys.journey_id = journeys.id
                        AND users.sub = ?
                )
            ORDER BY journeys.created_at DESC, journeys.uid ASC
            LIMIT 1
            """,
            (auth_result.result.sub,),
        )
        if not response.results:
            logging.info(f"No available ai journeys for {auth_result.result.sub}")
            return NONE_FOUND_RESPONSE

        journey_uid: str = response.results[0][0]
        journey_jwt = await create_journey_jwt(itgs, journey_uid=journey_uid)
        journey = await read_one_external(
            itgs, journey_uid=journey_uid, jwt=journey_jwt
        )
        if journey is None:
            logging.error(f"Failed to fetch journey {journey_uid}")
            return RACED_RESPONSE

        return journey
