import secrets
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal, Optional, cast
from journeys.lib.notifs import on_entering_lobby
from error_middleware import handle_contextless_error
from journeys.lib.read_one_external import read_one_external
from journeys.models.external_journey import ExternalJourney
from journeys.models.series_flags import SeriesFlags
from models import (
    AUTHORIZATION_UNKNOWN_TOKEN,
    StandardErrorResponse,
    STANDARD_ERRORS_BY_CODE,
)
import users.lib.entitlements as entitlements
from auth import auth_any
from itgs import Itgs
from journeys.auth import create_jwt as create_journey_jwt
from response_utils import cleanup_response
import time
import courses.auth
from users.lib.timezones import get_user_timezone
import unix_dates

router = APIRouter()


class StartJourneyRequest(BaseModel):
    journey_uid: str = Field(description="The UID of the journey you want to start")
    course_uid: str = Field(
        description="The UID of the course that you own that includes the journey"
    )
    course_jwt: Optional[str] = Field(
        None,
        description=(
            "If specified, must have the take journeys flag and is used instead of "
            "the revenue cat entitlement. This will be required in the future."
        ),
    )


ERROR_404_TYPES = Literal["journey_not_found"]
JOURNEY_NOT_FOUND_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="journey_not_found",
        message="That journey does not exist, or it is not in that course, or you do not own that course",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
)

ERROR_503_TYPES = Literal["journey_gone", "failed_to_start"]
JOURNEY_GONE_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_503_TYPES](
        type="journey_gone",
        message=(
            "The journey was deleted between you requesting it and us starting it. "
            "Retry in a few seconds."
        ),
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8", "Retry-After": "5"},
    status_code=503,
)
FAILED_TO_START_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_503_TYPES](
        type="failed_to_start",
        message=(
            "We failed to start the journey. This is probably a server error. "
            "Retry in a few seconds."
        ),
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8", "Retry-After": "5"},
    status_code=503,
)


@router.post(
    "/start_journey",
    response_model=ExternalJourney,
    responses={
        "404": {
            "description": "The journey was not found",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def start_journey(
    args: StartJourneyRequest, authorization: Optional[str] = Header(None)
):
    """Fetches a signed ref for the given journey, assuming that you own the course
    that the journey is in. Note that this does not advance the course; it's
    typically necessary for the client to consider if that would be appropriate
    given the context they are doing this in.

    This requires that the course has been attached already.

    Requires standard authorization
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        course_auth_result = (
            None
            if args.course_jwt is None
            else await courses.auth.auth_any(itgs, f"bearer {args.course_jwt}")
        )
        if course_auth_result is not None:
            if course_auth_result.result is None:
                return course_auth_result.error_response
            if (
                course_auth_result.result.course_uid != args.course_uid
                or (
                    course_auth_result.result.oseh_flags
                    & courses.auth.CourseAccessFlags.TAKE_JOURNEYS
                )
                == 0
            ):
                return AUTHORIZATION_UNKNOWN_TOKEN

        conn = await itgs.conn()
        cursor = conn.cursor("none")

        response = await cursor.execute(
            """
            SELECT 
                courses.title, 
                courses.slug, 
                courses.revenue_cat_entitlement 
            FROM courses 
            WHERE 
                courses.uid = ?
            """
            + (" AND (courses.flags & ?) != 0" if args.course_jwt is None else ""),
            (
                args.course_uid,
                *(
                    [int(SeriesFlags.SERIES_VISIBLE_IN_OWNED)]
                    if args.course_jwt is None
                    else []
                ),
            ),
        )
        if not response.results:
            return JOURNEY_NOT_FOUND_RESPONSE

        course_title = cast(str, response.results[0][0])
        course_slug = cast(str, response.results[0][1])
        revenue_cat_entitlement = cast(str, response.results[0][2])

        if args.course_jwt is None:
            entitlement_info = await entitlements.get_entitlement(
                itgs,
                user_sub=auth_result.result.sub,
                identifier=revenue_cat_entitlement,
            )
            if entitlement_info is None or not entitlement_info.is_active:
                return JOURNEY_NOT_FOUND_RESPONSE

        response = await cursor.execute(
            """
            SELECT
                1
            FROM journeys
            JOIN content_files AS audio_content_files ON audio_content_files.id = journeys.audio_content_file_id
            LEFT OUTER JOIN content_files AS video_content_files ON video_content_files.id = journeys.video_content_file_id
            WHERE
                journeys.uid = ?
                AND EXISTS (
                    SELECT 1 FROM course_journeys, courses
                    WHERE
                        course_journeys.course_id = courses.id
                        AND courses.uid = ?
                        AND course_journeys.journey_id = journeys.id
                )
            """,
            (args.journey_uid, args.course_uid),
        )
        if not response.results:
            return JOURNEY_NOT_FOUND_RESPONSE

        journey_jwt = await create_journey_jwt(itgs, journey_uid=args.journey_uid)
        journey_response = await read_one_external(
            itgs, journey_uid=args.journey_uid, jwt=journey_jwt
        )
        if journey_response is None:
            await handle_contextless_error(
                extra_info="while starting next journey in course, journey was gone"
            )
            return JOURNEY_GONE_RESPONSE

        course_user_classes_uid = f"oseh_cuc_{secrets.token_urlsafe(16)}"
        now = time.time()
        response = await cursor.execute(
            """
            INSERT INTO course_user_classes (
                uid, course_user_id, journey_id, created_at
            )
            SELECT
                ?, course_users.id, journeys.id, ?
            FROM courses, users, course_users, course_journeys, journeys
            WHERE
                courses.uid = ?
                AND users.sub = ?
                AND course_users.course_id = courses.id
                AND course_users.user_id = users.id
                AND course_journeys.course_id = courses.id
                AND course_journeys.journey_id = journeys.id
                AND journeys.uid = ?
            """,
            (
                course_user_classes_uid,
                now,
                args.course_uid,
                auth_result.result.sub,
                args.journey_uid,
            ),
        )
        if response.rows_affected is None or response.rows_affected < 1:
            await cleanup_response(journey_response)
            await handle_contextless_error(
                extra_info="while starting next journey in course, failed to store course_user_classes record"
            )
            return FAILED_TO_START_RESPONSE

        user_journey_uid = f"oseh_uj_{secrets.token_urlsafe(16)}"
        user_tz = await get_user_timezone(itgs, user_sub=auth_result.result.sub)
        created_at_unix_date = unix_dates.unix_timestamp_to_unix_date(now, tz=user_tz)
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
                now,
                created_at_unix_date,
                auth_result.result.sub,
                args.journey_uid,
            ),
        )
        if response.rows_affected is None or response.rows_affected < 1:
            await handle_contextless_error(
                extra_info="while starting next journey in course, failed to store user_journeys record"
            )

        await on_entering_lobby(
            itgs,
            user_sub=auth_result.result.sub,
            journey_uid=args.journey_uid,
            action=f"taking a class in {course_title} ({course_slug})",
        )

        return journey_response
