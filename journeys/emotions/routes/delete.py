from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal, Optional
from emotions.lib.emotion_content import purge_emotion_content_statistics_everywhere
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from itgs import Itgs


router = APIRouter()


class DeleteJourneyEmotionRequest(BaseModel):
    journey_uid: str = Field(
        description="the uid of the journey to remove the emotion from"
    )
    emotion: str = Field(description="The emotion word to remove from the journey")


ERROR_404_TYPES = Literal["relationship_not_found"]

ERROR_RELATIONSHIP_NOT_FOUND = Response(
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="relationship_not_found",
        message="There is no matching relationship between the journey and emotion",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=404,
)


@router.delete(
    "/",
    status_code=204,
    responses={
        "404": {
            "description": "The specified relationship does not exist to be deleted"
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def delete_journey_emotion(
    args: DeleteJourneyEmotionRequest, authorization: Optional[str] = Header(None)
):
    """Removes a relationship between a journey and an emotion.

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor()

        response = await cursor.execute(
            """
            DELETE FROM journey_emotions
            WHERE
                EXISTS (
                    SELECT 1 FROM journeys
                    WHERE
                        journeys.uid = ?
                        AND journeys.id = journey_emotions.journey_id
                )
                AND EXISTS (
                    SELECT 1 FROM emotions
                    WHERE
                        emotions.word = ?
                        AND emotions.id = journey_emotions.emotion_id
                )
            """,
            (args.journey_uid, args.emotion),
        )
        if response.rows_affected is None or response.rows_affected < 1:
            return ERROR_RELATIONSHIP_NOT_FOUND

        await purge_emotion_content_statistics_everywhere(itgs, emotions=[args.emotion])
        return Response(status_code=204)
