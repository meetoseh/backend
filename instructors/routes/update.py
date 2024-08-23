import json
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, StringConstraints
from typing import Literal, Optional, Annotated, cast
from auth import auth_admin
from instructors.lib.instructor_flags import ALL_INSTRUCTOR_FLAGS
from journeys.lib.read_one_external import evict_external_journey
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from itgs import Itgs


router = APIRouter()


class UpdateInstructorRequest(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] = (
        Field(description="The new display name for the instructor")
    )
    bias: float = Field(
        description=(
            "A non-negative number generally less than 1 that influences "
            "content selection towards this instructor."
        ),
        ge=0,
    )
    flags: int = Field(
        description=(
            "The new flags for the instructor, which is a bitfield. From least to most "
            "significant:\n"
            " - 0x01: unset to prevent the instructor from being shown by default in the admin area\n"
            " - 0x02: unset to prevent the instructor from being shown in the classes filter\n"
        )
    )


class UpdateInstructorResponse(BaseModel):
    name: str = Field(description="The new display name for the instructor")
    bias: float = Field(description="the new bias for the instructor")
    flags: int = Field(description="The new flags for the instructor")


ERROR_404_TYPES = Literal["instructor_not_found"]
INSTRUCTOR_NOT_FOUND_RESPONSE = Response(
    status_code=404,
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="instructor_not_found",
        message="The instructor was not found",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
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
    """Updates the simple fields on the instructor with the given uid.

    See also: `PUT {uid}/pictures/` to update the instructor's profile picture.

    This requires standard authentication and can only be done by admin users.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor("none")

        clean_flags = args.flags & int(ALL_INSTRUCTOR_FLAGS)

        response = await cursor.executeunified3(
            (
                (
                    """
SELECT name FROM instructors WHERE uid = ?
                    """,
                    (uid,),
                ),
                (
                    """
UPDATE instructors
SET name = ?, bias = ?, flags = ?
WHERE uid = ?
                    """,
                    (args.name, args.bias, clean_flags, uid),
                ),
            ),
        )

        if not response[0].results:
            assert (
                response[1].rows_affected is None or response[1].rows_affected == 0
            ), response
            return INSTRUCTOR_NOT_FOUND_RESPONSE

        assert response[1].rows_affected == 1, response
        old_name = cast(str, response[0].results[0][0])

        success_response = Response(
            status_code=200,
            content=UpdateInstructorResponse(
                name=args.name, bias=args.bias, flags=clean_flags
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

        if biggest_journey_id != 0:
            redis = await itgs.redis()
            await redis.set(
                b"journey_embeddings_needs_refresh",
                json.dumps({"reason": "instructor-patched", "at": time.time()}).encode(
                    "utf-8"
                ),
            )

        return success_response
