import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal, Optional
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from journeys.lib.read_one_external import evict_external_journey
from emotions.lib.emotion_content import purge_emotion_content_statistics_everywhere
from auth import auth_admin
from itgs import Itgs


class DeleteJourneyResponse(BaseModel):
    deleted_at: float = Field(
        description="The timestamp at which the journey was deleted, in seconds since the unix epoch"
    )


ERROR_404_TYPES = Literal["journey_not_found"]
ERROR_409_TYPES = Literal["undeleted_variations"]


router = APIRouter()


@router.delete(
    "/{uid}",
    status_code=200,
    response_model=DeleteJourneyResponse,
    responses={
        "404": {
            "description": "That journey does not exist or is already soft-deleted",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        "409": {
            "description": "That journey has undeleted variations",
            "model": StandardErrorResponse[ERROR_409_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def delete_journey(uid: str, authorization: Optional[str] = Header(None)):
    """Soft-deletes the journey with the given uid. This operation is reversible
    using `POST {uid}/undelete`

    This requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor("weak")

        now = time.time()

        response = await cursor.execute(
            """
            UPDATE journeys
            SET deleted_at = ?
            WHERE
                uid = ?
                AND deleted_at IS NULL
                AND NOT EXISTS (
                    SELECT 1 FROM journeys AS variations
                    WHERE
                        variations.variation_of_journey_id = journeys.id
                        AND variations.deleted_at IS NULL
                )
            """,
            (now, uid),
        )
        if response.rows_affected is not None and response.rows_affected > 0:
            await evict_external_journey(itgs, uid=uid)
            await purge_emotion_content_statistics_everywhere(itgs)
            return Response(
                content=DeleteJourneyResponse(deleted_at=now).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=200,
            )

        response = await cursor.execute(
            """
            SELECT
                variations.uid
            FROM journeys, journeys AS variations
            WHERE
                journeys.uid = ?
                AND variations.variation_of_journey_id = journeys.id
                AND variations.deleted_at IS NULL
            """,
            (uid,),
        )

        if response.results:
            return Response(
                content=StandardErrorResponse[ERROR_409_TYPES](
                    type="undeleted_variations",
                    message=(
                        "This journey has the following undeleted variations: "
                        + ", ".join(r[0] for r in response.results)
                    ),
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=409,
            )

        return Response(
            content=StandardErrorResponse[ERROR_404_TYPES](
                type="journey_not_found",
                message=(
                    "The journey with that uid was not found, or it was changed during this delete, "
                    "or it may already be soft-deleted"
                ),
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=404,
        )
