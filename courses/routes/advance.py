import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal, Optional
from itgs import Itgs
from auth import auth_any
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
import users.lib.entitlements


router = APIRouter()


class AdvanceCourseRequest(BaseModel):
    course_uid: str = Field(
        description="The UID of the course that you want to advance"
    )
    journey_uid: str = Field(
        description="The UID of the journey that the user has taken, for idempotency"
    )


class AdvanceCourseResponse(BaseModel):
    new_next_journey_uid: Optional[str] = Field(
        description="The UID of the next journey in the course after this operation, if there is one"
    )


ERROR_404_TYPES = Literal["not_found"]
NOT_FOUND_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="not_found",
        message=(
            "You either have not started that course, have already finished it, "
            "or don't have access to it."
        ),
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=404,
)

ERROR_409_TYPES = Literal["journey_is_not_next"]
JOURNEY_IS_NOT_NEXT_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_409_TYPES](
        type="journey_is_not_next",
        message=(
            "Although you do have access to that course, the next journey "
            "in the course differs from the one specified. This indicates either "
            "the course was changed under you or the course was advanced "
            "in a different window/tab."
        ),
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=409,
)


@router.post(
    "/advance",
    status_code=200,
    response_model=AdvanceCourseResponse,
    responses={
        "404": {
            "description": "The course was not found or the user is not entitled to it",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        "409": {
            "description": (
                "The journey specified is not the next journey in the course. "
                "This indicates either the course was changed under you or the "
                "course was advanced in a different window/tab."
            ),
            "model": StandardErrorResponse[ERROR_409_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def advance_course(
    args: AdvanceCourseRequest, authorization: Optional[str] = Header(None)
):
    """Advances the course with the given uid for the user, so that start_next now
    gives the next journey in the course (if there is one), and so that `mine`
    now has a new `last_journey_at` timestamp for filtering.

    This should be called after the user has successfully started playing audio in
    the journey for the course.

    This will only advance the course if the user is currently on the journey with
    the given uid in that course. This ensures this endpoint is relatively idempotent,
    especially when there aren't any duplicate journeys - which should be the common
    case.

    Requires standard authorization for a user entitled to the given course and who
    has started but not yet completed that course.
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
                (
                    (
                        course_users.last_priority IS NULL
                        OR course_journeys.priority > course_users.last_priority
                    )
                    AND NOT EXISTS (
                        SELECT 1 FROM course_journeys AS cj2
                        WHERE
                            cj2.course_id = courses.id
                            AND cj2.priority < course_journeys.priority
                            AND (
                                course_users.last_priority IS NULL
                                OR cj2.priority > course_users.last_priority
                            )
                    )
                ) AS is_next_journey,
                courses.title,
                courses.slug,
                course_journeys.priority
            FROM courses, users, course_users, course_journeys, journeys
            WHERE
                courses.uid = ?
                AND users.sub = ?
                AND course_users.user_id = users.id
                AND course_users.course_id = courses.id
                AND course_journeys.course_id = courses.id
                AND course_journeys.journey_id = journeys.id
                AND journeys.uid = ?
            """,
            (args.course_uid, auth_result.result.sub, args.journey_uid),
        )
        if not response.results:
            return NOT_FOUND_RESPONSE

        best_row = response.results[0]
        for row in response.results:
            if bool(row[1]):
                best_row = row
                break

        entitlement_iden: str = best_row[0]
        is_next_journey: bool = bool(best_row[1])
        course_title: str = best_row[2]
        course_slug: str = best_row[3]
        course_journey_priority: int = best_row[4]

        entitlement = await users.lib.entitlements.get_entitlement(
            itgs, user_sub=auth_result.result.sub, identifier=entitlement_iden
        )
        if entitlement is None or not entitlement.is_active:
            return NOT_FOUND_RESPONSE

        if not is_next_journey:
            return JOURNEY_IS_NOT_NEXT_RESPONSE

        response = await cursor.execute(
            """
            UPDATE course_users
            SET last_priority = course_journeys.priority, last_journey_at = ?
            FROM courses, users, course_journeys, journeys
            WHERE
                courses.uid = ?
                AND users.sub = ?
                AND course_users.user_id = users.id
                AND course_users.course_id = courses.id
                AND course_journeys.course_id = courses.id
                AND course_journeys.journey_id = journeys.id
                AND journeys.uid = ?
                AND (
                    course_users.last_priority IS NULL
                    OR course_journeys.priority > course_users.last_priority
                )
                AND NOT EXISTS (
                    SELECT 1 FROM course_journeys AS cj2
                    WHERE
                        cj2.course_id = courses.id
                        AND cj2.priority < course_journeys.priority
                        AND (
                            course_users.last_priority IS NULL
                            OR cj2.priority > course_users.last_priority
                        )
                )
            """,
            (time.time(), args.course_uid, auth_result.result.sub, args.journey_uid),
        )
        if response.rows_affected is None or response.rows_affected < 1:
            return JOURNEY_IS_NOT_NEXT_RESPONSE

        response = await cursor.execute(
            """
            SELECT
                journeys.uid
            FROM course_journeys, journeys, courses
            WHERE
                course_journeys.course_id = courses.id
                AND course_journeys.journey_id = journeys.id
                AND courses.uid = ?
                AND course_journeys.priority > ?
            ORDER BY course_journeys.priority ASC
            LIMIT 1
            """,
            (
                args.course_uid,
                course_journey_priority,
            ),
            read_consistency="none",
        )
        next_journey_uid: Optional[str] = None
        if response.results:
            next_journey_uid = response.results[0][0]

        return Response(
            content=AdvanceCourseResponse(
                new_next_journey_uid=next_journey_uid,
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=200,
        )
