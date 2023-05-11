from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Optional
from error_middleware import handle_contextless_error
from models import STANDARD_ERRORS_BY_CODE
from auth import auth_any
from itgs import Itgs
from emotions.lib.emotion_users import on_started_emotion_user_journey
from journeys.lib.notifs import on_entering_lobby

router = APIRouter()


class StartedRelatedJourneyRequest(BaseModel):
    emotion_user_uid: str = Field(
        description="The emotion/user record whose journey was started"
    )


@router.post(
    "/started_related_journey",
    status_code=204,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def started_related_journey(
    args: StartedRelatedJourneyRequest,
    authorization: Optional[str] = Header(None),
):
    """Tracks that the user has decided to actually start the journey
    associated with the given emotion/user record. This ensures that the
    users history is accurate, and they won't be personalized towards
    content they haven't actually seen.

    Requires standard authorization for the same user in the emotion/user record.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor("weak")

        response = await cursor.execute(
            """
            SELECT
                journeys.uid,
                emotions.word
            FROM emotion_users, journeys, emotions
            WHERE
                emotion_users.uid = ?
                AND emotion_users.journey_id = journeys.id
                AND emotion_users.emotion_id = emotions.id
                AND EXISTS (
                    SELECT 1 FROM users
                    WHERE
                        users.sub = ?
                        AND users.id = emotion_users.user_id
                )
            """,
            (args.emotion_user_uid, auth_result.result.sub),
        )
        if not response.results:
            await handle_contextless_error(
                extra_info=f"started_related_journey, failed to fetch record for {args.emotion_user_uid} and {auth_result.result.sub}"
            )
            return Response(status_code=204)

        journey_uid: Optional[str] = response.results[0][0]
        emotion_word: str = response.results[0][1]

        await on_started_emotion_user_journey(
            itgs,
            emotion_user_uid=args.emotion_user_uid,
            user_sub=auth_result.result.sub,
        )

        if journey_uid is not None:
            await on_entering_lobby(
                itgs,
                user_sub=auth_result.result.sub,
                journey_uid=journey_uid,
                action=f"entering a lobby for {emotion_word}",
            )
        else:
            await handle_contextless_error(
                extra_info=f"started_related_journey, journey_uid lost for {args.emotion_user_uid}"
            )

        return Response(status_code=204)
