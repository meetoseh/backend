from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, StringConstraints
from typing import Literal, Optional, Annotated
from auth import auth_admin
from journeys.lib.read_one_external import evict_external_journey
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from itgs import Itgs


router = APIRouter()


class UpdateInstructorRequest(BaseModel):
    name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1)
    ] = Field(description="The new display name for the instructor")
    bias: float = Field(
        description=(
            "A non-negative number generally less than 1 that influences "
            "content selection towards this instructor."
        ),
        ge=0,
    )


class UpdateInstructorResponse(BaseModel):
    name: str = Field(description="The new display name for the instructor")
    bias: float = Field(description="the new bias for the instructor")


ERROR_404_TYPES = Literal["instructor_not_found"]
INSTRUCTOR_NOT_FOUND_RESPONSE = Response(
    status_code=404,
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="instructor_not_found",
        message="The instructor was not found or is deleted",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
)

ERROR_503_TYPES = Literal["raced"]
RACED_RESPONSE = Response(
    status_code=503,
    content=StandardErrorResponse[ERROR_503_TYPES](
        type="raced",
        message="The instructor was updated by another request. Please try again.",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8", "Retry-After": "5"},
)


@router.put(
    "/{uid}",
    responses={
        "404": {
            "model": StandardErrorResponse[ERROR_404_TYPES],
            "description": "The instructor was not found or is deleted",
        },
        **STANDARD_ERRORS_BY_CODE,
    },
    response_model=UpdateInstructorResponse,
    status_code=200,
)
async def update_instructor(
    uid: str, args: UpdateInstructorRequest, authorization: Optional[str] = Header(None)
):
    """Updates the simple fields on the instructor with the given uid. This cannot
    be performed against soft-deleted instructors.

    See also: `PUT {uid}/pictures/` to update the instructor's profile picture.

    This requires standard authentication and can only be done by admin users.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor("none")

        response = await cursor.execute(
            """
            SELECT
                name, bias
            FROM instructors
            WHERE
                uid = ? AND deleted_at IS NULL
            """,
            (uid,),
        )
        if not response.results:
            return INSTRUCTOR_NOT_FOUND_RESPONSE

        old_name: str = response.results[0][0]
        old_bias: float = response.results[0][1]

        response = await cursor.execute(
            """
            UPDATE instructors
            SET name = ?, bias = ?
            WHERE uid = ? AND deleted_at IS NULL AND name=? AND bias=?
            """,
            (args.name, args.bias, uid, old_name, old_bias),
        )

        if response.rows_affected is None or response.rows_affected < 1:
            return RACED_RESPONSE

        success_response = Response(
            status_code=200,
            content=UpdateInstructorResponse(
                name=args.name, bias=args.bias
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )

        if old_name == args.name:
            return success_response

        biggest_journey_id = 0
        jobs = await itgs.jobs()
        while True:
            response = await cursor.execute(
                """
                SELECT
                    journeys.id, journeys.uid
                FROM journeys
                WHERE
                    EXISTS (
                        SELECT 1 FROM instructors
                        WHERE instructors.id = journeys.instructor_id
                          AND instructors.uid = ?
                    )
                    AND journeys.id > ?
                    AND journeys.deleted_at IS NULL
                ORDER BY journeys.id ASC
                LIMIT 100
                """,
                (
                    uid,
                    biggest_journey_id,
                ),
            )
            if not response.results:
                break

            for _, journey_uid in response.results:
                await evict_external_journey(itgs, uid=journey_uid)
                await jobs.enqueue(
                    "runners.process_journey_video_sample", journey_uid=journey_uid
                )
                await jobs.enqueue(
                    "runners.process_journey_video", journey_uid=journey_uid
                )

            biggest_journey_id = response.results[-1][0]

        return success_response
