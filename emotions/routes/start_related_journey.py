from fastapi import APIRouter, Header
from fastapi.responses import Response, StreamingResponse
from typing import AsyncIterator, List, Literal, Optional, Union
from pydantic import BaseModel, Field
from image_files.models import ImageFileRef
from journeys.models.external_journey import ExternalJourney
from journeys.lib.read_one_external import read_one_external
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from itgs import Itgs
from auth import auth_any
from journeys.auth import create_jwt as create_journey_jwt
from image_files.auth import create_jwt as create_image_file_jwt
from personalization.lib.pipeline import select_journey
import emotions.lib.emotion_users as emotion_users

router = APIRouter()


class StartRelatedJourneyRequest(BaseModel):
    emotion: str = Field(description="The emotion word to find a journey for")
    replaced_emotion_user_uid: Optional[str] = Field(
        description=(
            "If this reuqest is because the user changed their mind before "
            "entering the class, the uid of the returned emotion/user "
            "relationship that is being replaced by this request."
        )
    )


class StartRelatedJourneyResponse(BaseModel):
    journey: ExternalJourney = Field(
        description="The journey that the user can now join"
    )
    emotion_user_uid: str = Field(
        description=(
            "The uid of the emotion/user relationship that was created, for "
            "correctly tracking the users history if the user doens't actually "
            "join the journey"
        )
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
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=404,
)

ERROR_503_TYPES = Literal["journey_not_found"]
ERROR_JOURNEY_NOT_FOUND = Response(
    content=StandardErrorResponse[ERROR_503_TYPES](
        type="journey_not_found",
        message="The selected journey was deleted while you were joining it",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8", "Retry-After": "5"},
    status_code=503,
)


async def _buffered_yield(inner: AsyncIterator[Union[str, bytes]]):
    buffer: bytes = b""
    async for chunk in inner:
        buffer += (
            chunk
            if isinstance(chunk, (bytes, bytearray, memoryview))
            else chunk.encode("utf-8")
        )
        if len(buffer) > 8192:
            yield buffer
            buffer = b""
    if len(buffer) > 0:
        yield buffer


async def _yield_response_from_nested(
    journey: Response,
    emotion_user_uid: str,
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

    yield b',"emotion_user_uid":"'
    yield emotion_user_uid.encode("ascii")
    yield b'","num_votes":'
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
        yield voter_picture.model_dump_json().encode("utf-8")
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
    Since this should be done eagerly, in order to track when the user actually starts
    this journey, use `started_related_journey`. Similarly, if the user decides to
    take a different journey, call this again with `replaced_emotion_user_uid` to
    track that the user changed their mind.

    Requires standard authorization.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        journey_uid = await select_journey(
            itgs, emotion=args.emotion, user_sub=auth_result.result.sub
        )
        if journey_uid is None:
            return ERROR_EMOTION_NOT_FOUND

        journey_jwt = await create_journey_jwt(itgs, journey_uid)
        journey = await read_one_external(
            itgs, journey_uid=journey_uid, jwt=journey_jwt
        )
        if journey is None:
            return ERROR_JOURNEY_NOT_FOUND

        on_choose_word_result = await emotion_users.on_choose_word(
            itgs,
            word=args.emotion,
            user_sub=auth_result.result.sub,
            journey_uid=journey_uid,
            replaced_emotion_user_uid=args.replaced_emotion_user_uid,
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

        return StreamingResponse(
            content=_buffered_yield(
                _yield_response_from_nested(
                    journey=journey,
                    emotion_user_uid=on_choose_word_result.emotion_user_uid,
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
