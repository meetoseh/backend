from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal, cast
from journeys.models.series_flags import SeriesFlags
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from itgs import Itgs
import os


router = APIRouter()


class ReadCanonicalJourneyUrlResponse(BaseModel):
    uid: str = Field(description="The UID of the journey")
    url: str = Field(
        description="The canonical url where the given journey can be found or previewed"
    )


ERROR_404_TYPES = Literal["not_found"]
ERROR_NOT_FOUND_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_404_TYPES].__pydantic_serializer__.to_json(
        StandardErrorResponse[ERROR_404_TYPES](
            type="not_found",
            message="There is no journey with that uid or it has no canonical url",
        )
    ),
    status_code=404,
    headers={"Content-Type": "application/json; charset=utf-8"},
)


@router.get(
    "/canonical_url/{uid}",
    response_model=ReadCanonicalJourneyUrlResponse,
    responses={
        **STANDARD_ERRORS_BY_CODE,
        "404": {
            "description": "The journey with the given uid does not exit or has no canonical url",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
    },
)
async def read_journey_canonical_url(uid: str):
    """Fetches the canonical public URL for the journey with the given UID.
    The journey will be generally describes at the given url, though it may
    not be completely watchable for everyone.
    """
    async with Itgs() as itgs:
        conn = await itgs.conn()
        cursor = conn.cursor("none")

        response = await cursor.execute(
            """
            SELECT journey_slugs.slug FROM journeys, journey_slugs 
            WHERE
                journey_slugs.journey_id = journeys.id
                AND journeys.uid = ?
                AND NOT EXISTS (
                    SELECT 1 FROM journey_slugs AS js
                    WHERE
                        journey_slugs.journey_id = js.journey_id
                        AND (
                            js.primary_at > journey_slugs.primary_at
                            OR (
                                js.primary_at = journey_slugs.primary_at
                                AND js.slug < journey_slugs.slug
                            )
                        )
                )
                AND journeys.deleted_at IS NULL
                AND journeys.special_category IS NULL
                AND NOT EXISTS (
                    SELECT 1 FROM course_journeys, courses
                    WHERE 
                        course_journeys.journey_id = journeys.id
                        AND courses.id = course_journeys.course_id
                        AND (courses.flags & ?) = 0
                )
            """,
            (uid, int(SeriesFlags.JOURNEYS_IN_SERIES_PUBLIC_SHAREABLE)),
        )

        if not response.results:
            return ERROR_NOT_FOUND_RESPONSE

        root_frontend_url = os.environ["ROOT_FRONTEND_URL"]
        slug = cast(str, response.results[0][0])

        return Response(
            content=ReadCanonicalJourneyUrlResponse.__pydantic_serializer__.to_json(
                ReadCanonicalJourneyUrlResponse(
                    uid=uid, url=f"{root_frontend_url}/shared/{slug}"
                )
            ),
            status_code=200,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "public, max-age=300, stale-while-revalidate=86400",
            },
        )
