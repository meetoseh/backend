import secrets
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal, Optional
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from emotions.lib.emotion_content import purge_emotion_content_statistics_everywhere
from itgs import Itgs
from journeys.emotions.models import (
    JourneyEmotion,
    JourneyEmotionCreationHintManual,
)

router = APIRouter()


class CreateJourneyEmotionRequest(BaseModel):
    journey_uid: str = Field(description="the uid of the journey to add the emotion to")
    emotion: str = Field(description="The emotion word to attach to the journey")


ERROR_404_TYPES = Literal["journey_not_found", "emotion_not_found"]
ERROR_409_TYPES = Literal["emotion_already_attached_to_journey"]
ERROR_503_TYPES = Literal["raced"]

ERROR_JOURNEY_NOT_FOUND = Response(
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="journey_not_found", message="There is no journey with the provided uid"
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=404,
)

ERROR_EMOTION_NOT_FOUND = Response(
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="emotion_not_found",
        message="There is no matching emotion; emotions must be created before they can be attached to journeys",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=404,
)

ERROR_EMOTION_ALREADY_ATTACHED_TO_JOURNEY = Response(
    content=StandardErrorResponse[ERROR_409_TYPES](
        type="emotion_already_attached_to_journey",
        message="The emotion is already attached to the journey",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=409,
)

ERROR_COULD_NOT_DETERMINE_FAILURE_REASON = Response(
    content=StandardErrorResponse[ERROR_503_TYPES](
        type="raced",
        message=(
            "The request failed because the emotion or journey does not exist or the "
            "emotion is already attached to the journey. However, it could not be "
            "determined which of these was the case."
        ),
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8", "Retry-After": "5"},
    status_code=503,
)


@router.post(
    "/",
    status_code=201,
    response_model=JourneyEmotion,
    responses={
        "404": {
            "description": "The journey or emotion was not found",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        "409": {
            "description": "The emotion is already attached to the journey",
            "model": StandardErrorResponse[ERROR_409_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def create_journey_emotion(
    args: CreateJourneyEmotionRequest, authorization: Optional[str] = Header(None)
):
    """Attaches the given emotion to the given journey, if it's not already attached and
    the journey and emotion both exist.

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor("weak")

        je_uid = f"oseh_je_{secrets.token_urlsafe(16)}"
        now = time.time()
        creation_hint = JourneyEmotionCreationHintManual(
            type="manual",
            user_sub=auth_result.result.sub,
        )
        response = await cursor.execute(
            """
            INSERT INTO journey_emotions (
                uid,
                journey_id,
                emotion_id,
                creation_hint,
                created_at
            )
            SELECT
                ?, journeys.id, emotions.id, ?, ?
            FROM journeys, emotions
            WHERE
                journeys.uid = ?
                AND emotions.word = ?
                AND NOT EXISTS (
                    SELECT 1 FROM journey_emotions AS je2
                    WHERE
                        je2.journey_id = journeys.id
                        AND je2.emotion_id = emotions.id
                )
            """,
            (
                je_uid,
                creation_hint.model_dump_json(),
                now,
                args.journey_uid,
                args.emotion,
            ),
        )
        if response.rows_affected is not None and response.rows_affected > 0:
            await purge_emotion_content_statistics_everywhere(
                itgs, emotions=[args.emotion]
            )
            return Response(
                content=JourneyEmotion(
                    uid=je_uid,
                    journey_uid=args.journey_uid,
                    emotion=args.emotion,
                    creation_hint=creation_hint,
                    created_at=now,
                ).model_dump_json(),
                status_code=201,
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        response = await cursor.execute(
            """
            SELECT
                EXISTS (SELECT 1 FROM emotions WHERE word = ?) AS b1,
                EXISTS (SELECT 1 FROM journeys WHERE uid = ?) AS b2,
                EXISTS (
                    SELECT 1 FROM journeys, emotions, journey_emotions
                    WHERE
                        journeys.uid = ?
                        AND emotions.word = ?
                        AND journeys.id = journey_emotions.journey_id
                        AND emotions.id = journey_emotions.emotion_id
                ) AS b3
            """,
            (
                args.emotion,
                args.journey_uid,
                args.journey_uid,
                args.emotion,
            ),
        )

        assert response.results is not None, response
        emotion_exists = bool(response.results[0])
        journey_exists = bool(response.results[1])
        emotion_already_attached_to_journey = bool(response.results[2])

        if not emotion_exists:
            return ERROR_EMOTION_NOT_FOUND
        elif not journey_exists:
            return ERROR_JOURNEY_NOT_FOUND
        elif emotion_already_attached_to_journey:
            return ERROR_EMOTION_ALREADY_ATTACHED_TO_JOURNEY
        return ERROR_COULD_NOT_DETERMINE_FAILURE_REASON
