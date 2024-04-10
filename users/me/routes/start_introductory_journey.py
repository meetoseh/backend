import os
import secrets
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from typing import Literal, Optional
from error_middleware import handle_contextless_error
from journeys.models.external_journey import ExternalJourney
from journeys.lib.read_one_external import read_one_external
from auth import auth_any
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from itgs import Itgs
import journeys.auth
import unix_dates
from users.lib.timezones import get_user_timezone


router = APIRouter()


ERROR_503_TYPES = Literal["no_introductory_journeys", "raced"]


@router.post(
    "/start_introductory_journey",
    status_code=201,
    response_model=ExternalJourney,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def start_introductory_journey(
    uid: Optional[str] = None, authorization: Optional[str] = Header(None)
):
    """Starts the given introductory journey. These are journeys that have been
    identified as good first journeys for those just starting out with the
    platform.

    If the uid is specified, the journey with that uid is returned if it exists
    and is introductory. Otherwise, a random introductory journey is returned.

    Requires standard authorization.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        journey_uid = await get_journey_uid(itgs, uid)
        if journey_uid is None:
            return Response(
                status_code=503,
                content=StandardErrorResponse[ERROR_503_TYPES](
                    type="no_introductory_journeys",
                    message=("There are no introductory journeys available."),
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        jwt = await journeys.auth.create_jwt(itgs, journey_uid=journey_uid)
        journey_response = await read_one_external(
            itgs, journey_uid=journey_uid, jwt=jwt
        )
        if journey_response is None:
            return Response(
                status_code=503,
                content=StandardErrorResponse[ERROR_503_TYPES](
                    type="raced", message="Please try again in a moment."
                ).model_dump_json(),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Retry-After": "5",
                },
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
                journey_uid,
            ),
        )
        if response.rows_affected is None or response.rows_affected < 1:
            await handle_contextless_error(
                extra_info=f"failed to store introductory journey user_journey row: {auth_result.result.sub=}, {journey_uid=}"
            )

        return journey_response


async def get_journey_uid(itgs: Itgs, uid: Optional[str]) -> Optional[str]:
    """Determines what introductory journey corresponds to the given uid, or
    a random introductory journey, or None if there are no introductory journeys.
    """
    conn = await itgs.conn()
    cursor = conn.cursor("none")

    if uid is not None:
        response = await cursor.execute(
            """
            SELECT 1 FROM journeys
            WHERE
                EXISTS (
                    SELECT 1 FROM introductory_journeys
                    WHERE introductory_journeys.journey_id = journeys.id
                )
                AND journeys.uid = ?
                AND journeys.deleted_at IS NULL
            """,
            (uid,),
        )
        if response.results:
            return uid

        if os.environ["ENVIRONMENT"] != "dev":
            await handle_contextless_error(
                extra_info=f"ignored request for introductory journey with invalid {uid=}"
            )

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
        await handle_contextless_error(
            extra_info="no undeleted introductory journeys found, fetching an arbitrary undeleted journey instead"
        )
        response = await cursor.execute(
            "SELECT uid FROM journeys WHERE deleted_at IS NULL LIMIT 1"
        )
        if not response.results:
            await handle_contextless_error(
                extra_info="no undeleted journeys found, returning None for intro journey"
            )
            return None

    return secrets.choice(response.results)[0]
