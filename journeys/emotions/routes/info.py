import json
from fastapi import APIRouter, Header
from fastapi.responses import Response
from journeys.emotions.models import JourneyEmotion
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from typing import Literal, Optional
from auth import auth_admin
from itgs import Itgs


router = APIRouter()


ERROR_404_TYPES = Literal["journey_emotion_not_found"]

ERROR_JOURNEY_EMOTION_NOT_FOUND = Response(
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="journey_emotion_not_found",
        message="There is no matching relationship between the journey and emotion",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=404,
)


@router.get(
    "/",
    response_model=JourneyEmotion,
    responses={
        "404": {
            "description": "The specified relationship does not exist",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def get_journey_emotion_info(
    journey_uid: str,
    emotion: str,
    authorization: Optional[str] = Header(None),
):
    """Gets information about a relationship between a journey and an emotion.

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
            SELECT
                journey_emotions.uid,
                journey_emotions.creation_hint,
                journey_emotions.created_at
            FROM journey_emotions, journeys, emotions
            WHERE
                journey_emotions.journey_id = journeys.id
                AND journeys.uid = ?
                AND journey_emotions.emotion_id = emotions.id
                AND emotions.word = ?
            """,
            (journey_uid, emotion),
        )
        if not response.results:
            return ERROR_JOURNEY_EMOTION_NOT_FOUND

        return Response(
            content=JourneyEmotion(
                uid=response.results[0][0],
                journey_uid=journey_uid,
                emotion=emotion,
                creation_hint=json.loads(response.results[0][1]),
                created_at=response.results[0][2],
            ).model_dump_json(),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "private, max-age=60",
            },
            status_code=200,
        )
