import secrets
from fastapi import APIRouter, Header
from fastapi.responses import Response
from typing import Literal, Optional
from pydantic import BaseModel, Field
from journeys.models.external_journey import ExternalJourney
from journeys.lib.read_one_external import read_one_external
from auth import auth_any
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from itgs import Itgs
import journeys.auth
from response_utils import cleanup_response


router = APIRouter()


ERROR_503_TYPES = Literal["no_introductory_journeys", "raced"]


@router.post(
    "/start_introductory_journey",
    status_code=201,
    response_model=ExternalJourney,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def start_introductory_journey(authorization: Optional[str] = Header(None)):
    """Starts a random introductory journey. These are journeys that have been
    identified as good first journeys for those just starting out with the
    platform.

    This endpoint can be called as many times as desired, and may return the
    same journey multiple times. However, it's primarily intended to only
    be used once per user immediately after logging in for the first time.

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
            SELECT journeys.uid FROM journeys
            WHERE
                EXISTS (
                    SELECT 1 FROM introductory_journeys
                    WHERE introductory_journeys.journey_id = journeys.id
                )
                AND journeys.deleted_at IS NULL
            """
        )
        if not response.results:
            return Response(
                status_code=503,
                content=StandardErrorResponse[ERROR_503_TYPES](
                    type="no_introductory_journeys",
                    message=("There are no introductory journeys available."),
                ).json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        journey_uid = secrets.choice(response.results)[0]

        # preparation
        session_uid = f"oseh_js_{secrets.token_urlsafe(16)}"
        jwt = await journeys.auth.create_jwt(itgs, journey_uid=journey_uid)

        # fetch info
        journey_response = await read_one_external(
            itgs, journey_uid=journey_uid, session_uid=session_uid, jwt=jwt
        )
        if journey_response is None:
            return Response(
                status_code=503,
                content=StandardErrorResponse[ERROR_503_TYPES](
                    type="raced", message="Please try again in a moment."
                ).json(),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Retry-After": "5",
                },
            )

        # insert session
        conn = await itgs.conn()
        cursor = conn.cursor("weak")
        response = await cursor.execute(
            """
            INSERT INTO journey_sessions (
                journey_id,
                user_id,
                uid
            )
            SELECT
                journeys.id,
                users.id,
                ?
            FROM journeys, users
            WHERE
                journeys.uid = ?
                AND users.sub = ?
            """,
            (
                session_uid,
                journey_uid,
                auth_result.result.sub,
            ),
        )
        if response.rows_affected is None or response.rows_affected < 1:
            await cleanup_response(journey_response)
            return Response(
                status_code=503,
                content=StandardErrorResponse[ERROR_503_TYPES](
                    type="raced", message="Please try again in a moment."
                ).json(),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Retry-After": "5",
                },
            )

        return journey_response
