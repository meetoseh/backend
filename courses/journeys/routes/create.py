import secrets
from fastapi import APIRouter, Header
from fastapi.responses import Response
from typing import Annotated, Literal, Optional
from pydantic import BaseModel, Field
from courses.journeys.models.internal_course_journey import (
    InternalCourseJourney,
    create_read_select,
    parse_read_result,
)
from error_middleware import handle_warning
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from auth import auth_admin
from itgs import Itgs


router = APIRouter()


class CreateCourseJourneyRequest(BaseModel):
    journey_uid: str = Field(description="The unique identifier for the journey")
    course_uid: str = Field(description="The unique identifier for the course")
    priority: int = Field(
        description="Journeys with lower priority values are generally taken first"
    )


ERROR_404_TYPES = Literal["journey_not_found", "course_not_found"]
ERROR_409_TYPES = Literal["priority_conflict"]


@router.post(
    "/",
    status_code=201,
    response_model=InternalCourseJourney,
    responses={
        "404": {
            "description": "The specified journey or course was not found",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        "409": {
            "description": "The specified priority is already in use for this course",
            "model": StandardErrorResponse[ERROR_409_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def create_course_journey(
    args: CreateCourseJourneyRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Associates the given journey with the given course with the given priority.
    This does not immediately result in the course export to be reproduced, thus
    the course may temporarily be in an inconsistent state.

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor("strong")

        new_course_journey_uid = f"oseh_cj_{secrets.token_urlsafe(16)}"
        response = await cursor.executeunified3(
            (
                ("SELECT 1 FROM journeys WHERE uid = ?", (args.journey_uid,)),
                ("SELECT 1 FROM courses WHERE uid = ?", (args.course_uid,)),
                (
                    """
SELECT course_journeys.uid FROM course_journeys, courses
WHERE
    course_journeys.course_id = courses.id
    AND courses.uid = ?
    AND course_journeys.priority = ?
                    """,
                    (args.course_uid, args.priority),
                ),
                (
                    """
INSERT INTO course_journeys (
    uid, course_id, journey_id, priority
)
SELECT
    ?,
    courses.id,
    journeys.id,
    ?
FROM courses, journeys
WHERE
    courses.uid = ?
    AND journeys.uid = ?
    AND NOT EXISTS (
        SELECT 1 FROM course_journeys AS cj
        WHERE
            cj.course_id = courses.id
            AND cj.priority = ?
    )
                    """,
                    (
                        new_course_journey_uid,
                        args.priority,
                        args.course_uid,
                        args.journey_uid,
                        args.priority,
                    ),
                ),
                (
                    f"{create_read_select()} WHERE course_journeys.uid = ?",
                    (new_course_journey_uid,),
                ),
            )
        )

        journey_response = response.items[0]
        course_response = response.items[1]
        priority_conflict_response = response.items[2]
        insert_response = response.items[3]
        read_response = response.items[4]

        did_insert = (
            insert_response.rows_affected is not None
            and insert_response.rows_affected > 0
        )
        if did_insert and insert_response.rows_affected != 1:
            await handle_warning(
                f"{__name__}:multiple_rows_inserted",
                f"expected to insert 1 row, but inserted {insert_response.rows_affected}",
                is_urgent=True,
            )

        if not journey_response.results:
            assert not did_insert, response
            return Response(
                status_code=404,
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="journey_not_found",
                    message="there is no journey with that uid",
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        if not course_response.results:
            assert not did_insert, response
            return Response(
                status_code=404,
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="course_not_found",
                    message="there is no course with that uid",
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        if priority_conflict_response.results:
            assert not did_insert, response
            return Response(
                status_code=409,
                content=StandardErrorResponse[ERROR_409_TYPES](
                    type="priority_conflict",
                    message="the specified priority is already in use for this course",
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        if not did_insert:
            await handle_warning(
                f"{__name__}:no_rows_inserted",
                f"expected rows inserted: {response}",
                is_urgent=True,
            )
            return Response(
                status_code=500,
                content=StandardErrorResponse[Literal["internal_error"]](
                    type="internal_error",
                    message="no rows were inserted",
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        if not read_response.results or len(read_response.results) != 1:
            await handle_warning(
                f"{__name__}:wrong_number_rows_returned",
                f"expected 1 row, but got {read_response.results}",
                is_urgent=True,
            )
            return Response(
                status_code=500,
                content=StandardErrorResponse[Literal["internal_error"]](
                    type="internal_error",
                    message="wrong number of rows returned",
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        parsed = await parse_read_result(itgs, read_response)
        assert len(parsed) == 1

        return Response(
            status_code=201,
            content=parsed[0].__pydantic_serializer__.to_json(parsed[0]),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
