from fastapi import APIRouter, Header
from fastapi.responses import Response, StreamingResponse
from typing import AsyncIterator, List, Literal, Optional
from pydantic import BaseModel, Field
from image_files.models import ImageFileRef
from journeys.models.external_journey import ExternalJourney
from journeys.lib.read_one_external import read_one_external
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from itgs import Itgs
from auth import auth_any
from journeys.auth import create_jwt as create_journey_jwt
from image_files.auth import create_jwt as create_image_file_jwt
import emotions.lib.emotion_users as emotion_users
from journeys.lib.notifs import on_entering_lobby
import random

router = APIRouter()


class StartRelatedJourneyRequest(BaseModel):
    emotion: str = Field(description="The emotion word to find a journey for")


class StartRelatedJourneyResponse(BaseModel):
    journey: ExternalJourney = Field(
        description="The journey that the user can now join"
    )
    num_votes: int = Field(
        description="How many votes there are for the selected emotion"
    )
    num_total_votes: int = Field(
        description="How many votes there are for all emotions"
    )
    voter_pictures: List[ImageFileRef] = Field(
        description="Some profile pictures of users who voted for this emotion"
    )


ERROR_404_TYPES = Literal["emotion_not_found"]

ERROR_EMOTION_NOT_FOUND = Response(
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="emotion_not_found",
        message="There is no matching emotion",
    ).json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=404,
)

ERROR_503_TYPES = Literal["journey_not_found"]
ERROR_JOURNEY_NOT_FOUND = Response(
    content=StandardErrorResponse[ERROR_503_TYPES](
        type="journey_not_found",
        message="The selected journey was deleted while you were joining it",
    ).json(),
    headers={"Content-Type": "application/json; charset=utf-8", "Retry-After": "5"},
    status_code=503,
)


async def _buffered_yield(inner: AsyncIterator[bytes]):
    buffer = b""
    async for chunk in inner:
        buffer += chunk
        if len(buffer) > 8192:
            yield buffer
            buffer = b""
    if len(buffer) > 0:
        yield buffer


async def _yield_response_from_nested(
    journey: Response,
    num_votes: int,
    num_total_votes: int,
    voter_pictures: List[ImageFileRef],
):
    """Yields the jsonified bytes response, where the journey is already encoded.
    This can be much more efficient than deserializing and reserializing the journey.
    """
    yield b'{"journey":'
    if isinstance(journey, StreamingResponse):
        async for chunk in journey.body_iterator:
            yield chunk
    else:
        yield journey.body

    yield b',"num_votes":'
    yield str(num_votes).encode("ascii")
    yield b',"num_total_votes":'
    yield str(num_total_votes).encode("ascii")
    yield b',"voter_pictures":['
    first = True
    for voter_picture in voter_pictures:
        if first:
            first = False
        else:
            yield b","
        yield voter_picture.json().encode("utf-8")
    yield b"]}"


@router.post(
    "/start_related_journey",
    response_model=StartRelatedJourneyResponse,
    responses={
        404: {
            "description": "The emotion word was not found",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def start_related_journey(
    args: StartRelatedJourneyRequest, authorization: Optional[str] = Header(None)
):
    """Starts a journey related to the given emotion word. The selected journey is
    personalized to the given user.

    This also provides some inline information about how many votes there are for
    the selected emotion, which can be shown while waiting for the journey to load.

    Requires standard authorization.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor("none")

        response = await cursor.execute(
            """
            SELECT
                journeys.uid AS journey_uid,
                0 AS num_times_taken,
                journeys.created_at AS journey_created_at
            FROM journeys
            WHERE
                NOT EXISTS (
                    SELECT 1 FROM interactive_prompt_sessions, users
                    WHERE
                        users.sub = ?
                        AND interactive_prompt_sessions.user_id = users.id
                        AND (
                            interactive_prompt_sessions.interactive_prompt_id = journeys.interactive_prompt_id
                            OR EXISTS (
                                SELECT 1 FROM interactive_prompt_old_journeys
                                WHERE interactive_prompt_old_journeys.interactive_prompt_id = interactive_prompt_sessions.interactive_prompt_id
                                    AND interactive_prompt_old_journeys.journey_id = journeys.id
                            )
                        )
                )
                AND EXISTS (
                    SELECT 1 FROM journey_emotions, emotions
                    WHERE
                        journey_emotions.journey_id = journeys.id
                        AND journey_emotions.emotion_id = emotions.id
                        AND emotions.word = ?
                )
                AND journeys.deleted_at IS NULL
                AND NOT EXISTS (
                    SELECT 1 FROM course_journeys
                    WHERE course_journeys.journey_id = journeys.id
                )
            UNION ALL
            SELECT
                journeys.uid AS journey_uid,
                COUNT(*) AS num_times_taken,
                journeys.created_at AS journey_created_at
            FROM journeys, interactive_prompt_sessions, users
            WHERE
                users.sub = ?
                AND interactive_prompt_sessions.user_id = users.id
                AND (
                    interactive_prompt_sessions.interactive_prompt_id = journeys.interactive_prompt_id
                    OR EXISTS (
                        SELECT 1 FROM interactive_prompt_old_journeys
                        WHERE interactive_prompt_old_journeys.interactive_prompt_id = interactive_prompt_sessions.interactive_prompt_id
                        AND interactive_prompt_old_journeys.journey_id = journeys.id
                    )
                )
                AND EXISTS (
                    SELECT 1 FROM journey_emotions, emotions
                    WHERE
                        journey_emotions.journey_id = journeys.id
                        AND journey_emotions.emotion_id = emotions.id
                        AND emotions.word = ?
                )
                AND journeys.deleted_at IS NULL
                AND NOT EXISTS (
                    SELECT 1 FROM course_journeys
                    WHERE course_journeys.journey_id = journeys.id
                )
            GROUP BY journey_uid
            ORDER BY num_times_taken ASC, journey_created_at DESC
            LIMIT 5
            """,
            (
                auth_result.result.sub,
                args.emotion,
                auth_result.result.sub,
                args.emotion,
            ),
        )
        if not response.results:
            return ERROR_EMOTION_NOT_FOUND

        row = random.choice(response.results)
        journey_uid: str = row[0]
        journey_jwt = await create_journey_jwt(itgs, journey_uid)
        journey = await read_one_external(
            itgs, journey_uid=journey_uid, jwt=journey_jwt
        )
        if journey is None:
            return ERROR_JOURNEY_NOT_FOUND

        await emotion_users.on_choose_word(
            itgs, word=args.emotion, user_sub=auth_result.result.sub
        )
        info = await emotion_users.get_emotion_choice_information(
            itgs, word=args.emotion
        )
        picture_uids = await emotion_users.get_emotion_pictures(itgs, word=args.emotion)
        pictures = [
            ImageFileRef(
                uid=uid, jwt=await create_image_file_jwt(itgs, image_file_uid=uid)
            )
            for uid in picture_uids
        ]

        await on_entering_lobby(
            itgs,
            user_sub=auth_result.result.sub,
            journey_uid=journey_uid,
            action=f"entering a lobby for *{args.emotion}*",
        )

        return StreamingResponse(
            content=_buffered_yield(
                _yield_response_from_nested(
                    journey=journey,
                    num_votes=info.votes_for_word,
                    num_total_votes=info.votes_total,
                    voter_pictures=pictures,
                )
            ),
            headers={
                "Content-Type": "application/json; charset=utf-8",
            },
            status_code=200,
        )
