import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, constr
from typing import Literal, Optional
from auth import auth_admin
from daily_events.lib.read_one_external import evict_external_daily_event
from journeys.lib.read_one_external import evict_external_journey
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from itgs import Itgs


router = APIRouter()


class UpdateInstructorRequest(BaseModel):
    name: constr(strip_whitespace=True, min_length=1) = Field(
        description="The new display name for the instructor"
    )


class UpdateInstructorResponse(BaseModel):
    name: str = Field(description="The new display name for the instructor")


ERROR_404_TYPES = Literal["instructor_not_found"]


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
            UPDATE instructors
            SET name = ?
            WHERE uid = ? AND deleted_at IS NULL
            """,
            (args.name, uid),
        )

        if response.rows_affected is None or response.rows_affected < 1:
            return Response(
                status_code=404,
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="instructor_not_found",
                    message="The instructor was not found or is deleted",
                ).json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        # we'll only purge journeys which have a daily event that's pretty recent,
        # otherwise it's good enough to manually clear the cache
        to_clean_daily_events = set()
        biggest_journey_id = 0
        now = time.time()
        while True:
            response = await cursor.execute(
                """
                SELECT
                    journeys.id, journeys.uid, daily_events.uid
                FROM journeys
                JOIN daily_events ON EXISTS (
                    SELECT 1 FROM daily_event_journeys
                    WHERE daily_event_journeys.daily_event_id = daily_events.id
                      AND daily_event_journeys.journey_id = journeys.id
                )
                WHERE
                    EXISTS (
                        SELECT 1 FROM instructors
                        WHERE instructors.id = journeys.instructor_id
                          AND instructors.uid = ?
                    )
                    AND journeys.id > ?
                    AND journeys.deleted_at IS NULL
                    AND daily_events.available_at IS NOT NULL
                    AND daily_events.available_at BETWEEN ? AND ?
                ORDER BY journeys.id ASC
                LIMIT 100
                """,
                (
                    uid,
                    biggest_journey_id,
                    now - 60 * 60 * 24 * 7,
                    now + 60 * 60 * 24 * 7,
                ),
            )
            if not response.results:
                break

            for _, journey_uid, daily_event_uid in response.results:
                await evict_external_journey(itgs, uid=journey_uid)

                to_clean_daily_events.add(daily_event_uid)

            biggest_journey_id = response.results[-1][0]

        for daily_event_uid in to_clean_daily_events:
            await evict_external_daily_event(itgs, uid=daily_event_uid)

        return Response(
            status_code=200,
            content=UpdateInstructorResponse(name=args.name).json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
