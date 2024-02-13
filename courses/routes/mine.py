from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import List, Optional
from courses.models.external_course import ExternalCourse
from courses.lib.get_external_course_from_row import get_external_course_from_row
from itgs import Itgs
from auth import auth_any
from journeys.models.series_flags import SeriesFlags
from models import STANDARD_ERRORS_BY_CODE
import users.lib.entitlements


class ReadMyCoursesRequest(BaseModel):
    last_taken_at_after: float = Field(
        description=(
            "Only external courses which haven't been taken since this date are returned, "
            "specified in seconds since the epoch."
        )
    )


class ReadMyCoursesResponse(BaseModel):
    courses: List[ExternalCourse] = Field(
        description=(
            "The courses the user has started but not yet completed, matching the "
            "criteria specified in the request."
        )
    )


router = APIRouter()


@router.post(
    "/mine", response_model=ReadMyCoursesResponse, responses=STANDARD_ERRORS_BY_CODE
)
async def read_my_courses(
    args: ReadMyCoursesRequest, authorization: Optional[str] = Header(None)
):
    """Fetches what courses the user has started but not yet completed, and
    haven't taken since the specified date.

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
                courses.uid,
                courses.slug,
                courses.title,
                courses.description,
                background_images.uid,
                courses.revenue_cat_entitlement
            FROM courses
            LEFT OUTER JOIN image_files AS background_images ON background_images.id = courses.background_image_file_id
            LEFT OUTER JOIN image_files AS circle_images ON circle_images.id = courses.circle_image_file_id
            WHERE
                EXISTS (
                    SELECT 1 FROM course_users, users
                    WHERE
                        course_users.course_id = courses.id
                        AND users.id = course_users.user_id
                        AND users.sub = ?
                        AND EXISTS (
                            SELECT 1 FROM course_journeys
                            WHERE course_journeys.course_id = courses.id
                                AND (
                                    course_users.last_priority IS NULL
                                    OR course_journeys.priority > course_users.last_priority
                                )
                                AND NOT EXISTS (
                                    SELECT 1 FROM journeys
                                    WHERE journeys.id = course_journeys.journey_id
                                        AND journeys.deleted_at IS NOT NULL
                                )
                        )
                        AND (
                            course_users.last_journey_at IS NULL
                            OR course_users.last_journey_at < ?
                        )
                )
                AND (courses.flags & ?) != 0
            """,
            (auth_result.result.sub, args.last_taken_at_after, int(SeriesFlags.SERIES_VISIBLE_IN_OWNED)),
        )

        courses: List[ExternalCourse] = []
        for row in response.results or []:
            entitlement_iden: str = row[5]
            entitlement = await users.lib.entitlements.get_entitlement(
                itgs, user_sub=auth_result.result.sub, identifier=entitlement_iden
            )
            if entitlement is None or not entitlement.is_active:
                continue
            courses.append(
                await get_external_course_from_row(
                    itgs,
                    uid=row[0],
                    slug=row[1],
                    title=row[2],
                    description=row[3],
                    background_image_uid=row[4],
                )
            )

        return Response(
            content=ReadMyCoursesResponse.__pydantic_serializer__.to_json(ReadMyCoursesResponse(courses=courses)),
            status_code=200,
            headers={
                "Content-Type": "application/json; charset=utf-8",
            },
        )
