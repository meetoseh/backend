# user jwt + course uid -> external journey
# side effect:
#   sets the users progress in that course to the priority of the returned journey,
#   meaning this is not idempotent
import secrets
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal, Optional
from journeys.lib.notifs import on_entering_lobby
from error_middleware import handle_contextless_error
from journeys.lib.read_one_external import read_one_external
from journeys.models.external_journey import ExternalJourney
from journeys.models.series_flags import SeriesFlags
from models import (
    StandardErrorResponse,
    STANDARD_ERRORS_BY_CODE,
    AUTHORIZATION_UNKNOWN_TOKEN,
)
import users.lib.entitlements
from auth import auth_any
from itgs import Itgs
from journeys.auth import create_jwt as create_journey_jwt
from response_utils import cleanup_response
import time


router = APIRouter()


class StartNextJourneyInCourseRequest(BaseModel):
    course_uid: str = Field(
        description=(
            "The uid of the course you want to start the next journey in. If the "
            "user is not entitled to this course, regardless of "
        )
    )


ERROR_404_TYPES = Literal["not_found"]
NOT_FOUND_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="not_found",
        message=(
            "You either have not started that course or have already finished it."
        ),
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=404,
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
    "/start_next",
    response_model=ExternalJourney,
    responses={
        "404": {
            "description": "The user has not started the course or has already finished it.",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def start_next_journey_in_course(
    args: StartNextJourneyInCourseRequest, authorization: Optional[str] = Header(None)
):
    """Returns the next journey in a course for the user. If the user has not
    started the course or has already finished the course or the course does
    not exist, returns a 404. Otherwise, if the user is not entitled to the course
    returns a 403.

    This does not actually advance the users progress in the course. Do that by
    calling advance_course_progress.

    Requires standard authorization.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor("weak")

        response = await cursor.execute(
            """
            SELECT
                courses.revenue_cat_entitlement,
                courses.title,
                courses.slug,
                journeys.uid
            FROM courses, users, course_users, course_journeys, journeys
            WHERE
                courses.uid = ?
                AND users.sub = ?
                AND course_users.course_id = courses.id
                AND course_users.user_id = users.id
                AND course_journeys.course_id = courses.id
                AND course_journeys.journey_id = journeys.id
                AND (
                    course_users.last_priority IS NULL
                    OR course_users.last_priority < course_journeys.priority
                )
                AND (courses.flags & ?) != 0
            ORDER BY course_journeys.priority ASC
            LIMIT 1
            """,
            (args.course_uid, auth_result.result.sub, int(SeriesFlags.SERIES_VISIBLE_IN_OWNED)),
        )
        if not response.results:
            return NOT_FOUND_RESPONSE

        entitlement_iden: str = response.results[0][0]
        course_title: str = response.results[0][1]
        course_slug: str = response.results[0][2]
        journey_uid: str = response.results[0][3]

        entitlement = await users.lib.entitlements.get_entitlement(
            itgs, user_sub=auth_result.result.sub, identifier=entitlement_iden
        )
        if entitlement is None or not entitlement.is_active:
            return AUTHORIZATION_UNKNOWN_TOKEN

        journey_jwt = await create_journey_jwt(itgs, journey_uid=journey_uid)
        journey_response = await read_one_external(
            itgs, journey_uid=journey_uid, jwt=journey_jwt
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
                journey_uid,
            ),
        )
        if response.rows_affected is None or response.rows_affected < 1:
            await cleanup_response(journey_response)
            await handle_contextless_error(
                extra_info="while starting next journey in course, failed to store course_user_classes record"
            )
            return FAILED_TO_START_RESPONSE

        user_journey_uid = f"oseh_uj_{secrets.token_urlsafe(16)}"
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
            (user_journey_uid, now, auth_result.result.sub, journey_uid),
        )
        if response.rows_affected is None or response.rows_affected < 1:
            await handle_contextless_error(
                extra_info="while starting next journey in course, failed to store user_journeys record"
            )

        await on_entering_lobby(
            itgs,
            user_sub=auth_result.result.sub,
            journey_uid=journey_uid,
            action=f"considering taking the next class in {course_title} ({course_slug})",
        )

        return journey_response
