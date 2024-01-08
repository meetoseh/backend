import asyncio
import io
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Annotated, Awaitable, List, Optional, Union, cast
from content_files.lib.serve_s3_file import read_in_parts
from error_middleware import handle_warning
from transcripts.auth import auth_any
from models import AUTHORIZATION_UNKNOWN_TOKEN, STANDARD_ERRORS_BY_CODE
from lifespan import lifespan_handler
from itgs import Itgs
import perpetual_pub_sub as pps


router = APIRouter()


class TranscriptPhrase(BaseModel):
    """A single phrase within a transcript. Phrases are non-overlapping, but may
    not partition the content due to periods of silence.

    Only simple, single-speaker transcripts are supported at this time.
    """

    starts_at: float = Field(
        description="When this phrase begins, in seconds from the start of the recording"
    )
    ends_at: float = Field(
        description="When this phrase ends, in seconds from the start of the recording"
    )
    phrase: str = Field(description="The text of the phrase")


class Transcript(BaseModel):
    """A transcript of a recording"""

    # NOTE: this is referenced in redis/keys.md

    uid: str = Field(
        description="The primary stable external identifier for this transcript"
    )
    phrases: List[TranscriptPhrase] = Field(
        description="The phrases in this transcript, in ascending order of start time"
    )


@router.get(
    "/{uid}",
    response_model=Transcript,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def show_transcript(
    uid: str, authorization: Annotated[Optional[str], Header()] = None
):
    """Shows the transcript with the given uid.

    Requires authorization for the specific transcript. The transcript
    module itself is not responsible for providing the required JWT;
    it will usually come from the same source that provides the
    JWT for the content file.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        if auth_result.result.transcript_uid != uid:
            return AUTHORIZATION_UNKNOWN_TOKEN

        transcript = await get_transcript(itgs, uid)
        if transcript is None:
            await handle_warning(
                f"{__name__}:missing_transcript",
                f"Received valid JWT for transcript {uid=}, but no such transcript exists",
            )
            return AUTHORIZATION_UNKNOWN_TOKEN

        return transcript


async def get_transcript(itgs: Itgs, uid: str) -> Optional[Response]:
    """Fetches the transcript with the given uid from the nearest source,
    if it exists, otherwise returns None

    Args:
        itgs (Itgs): the integrations to (re)use
        uid (str): the uid of the transcript to fetch

    Returns:
        Response, None: the transcript, as a response, if one with the given
            uid exists, otherwise None. This operates at less-than-none
            consistency, meaning it has to exist for the whole function call and
            at least 5 minutes before (default cursor freshness) to be
            guarranteed to be found, and may be stale if changed (though
            transcripts should not change, rather, a new one should be created)

            This returns the transcript as a response in case it's possible to
            stream the transcript.
    """
    result = await get_transcript_from_local_cache(itgs, uid)
    if result is not None:
        return result

    result = await get_transcript_from_network_cache(itgs, uid)
    if result is not None:
        await write_transcript_to_local_cache(itgs, uid, result)
        return Response(
            content=result,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Content-Length": str(len(result)),
            },
            status_code=200,
        )

    result = await get_transcript_from_source(itgs, uid)
    if result is None:
        return None
    encoded_result = result.__pydantic_serializer__.to_json(result)
    await write_transcript_to_local_cache(itgs, uid, content=encoded_result)
    await write_transcript_to_network_cache(itgs, uid, content=encoded_result)
    await push_transcript_to_all_instances_local_cache(
        itgs, uid, content=encoded_result
    )
    return Response(
        content=encoded_result,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Content-Length": str(len(encoded_result)),
        },
        status_code=200,
    )


async def get_transcript_from_local_cache(itgs: Itgs, uid: str) -> Optional[Response]:
    """Attempts to get the transcript with the given uid from
    the local cache, if it exists, otherwise returns None.

    Args:
        itgs (Itgs): the integrations to (re)use
        uid (str): the uid of the transcript to fetch

    Returns:
        Response, None: The transcript within a response, if it's available,
            otherwise None. This streams the transcript from disk if it's
            sufficiently large
    """
    cache = await itgs.local_cache()
    raw = cast(
        Union[bytes, io.BytesIO, None],
        cache.get(f"transcripts:{uid}".encode("utf-8"), read=True),
    )
    if raw is None:
        return None
    if isinstance(raw, (bytes, bytearray, memoryview)):
        return Response(
            content=raw[8:],
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Content-Length": str(len(raw) - 8),
            },
            status_code=200,
        )

    content_length = int.from_bytes(raw.read(8), "big", signed=False)
    return Response(
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Content-Length": str(content_length),
        },
        content=read_in_parts(raw),
        status_code=200,
    )


async def write_transcript_to_local_cache(itgs: Itgs, uid: str, content: bytes) -> None:
    """Writes the given serialized transcript to the local cache.

    Args:
        itgs (Itgs): the integrations to (re)use
        uid (str): the uid of the transcript to write
        content (bytes): the serialized transcript to write, as if from
            `transcript.model_dump_json().encode('utf-8')`
    """
    encoded_length = len(content).to_bytes(8, "big", signed=False)
    total_to_write = encoded_length + content

    cache = await itgs.local_cache()
    cache.set(f"transcripts:{uid}".encode("utf-8"), total_to_write)


async def get_transcript_from_network_cache(itgs: Itgs, uid: str) -> Optional[bytes]:
    """Attempts to get the transcript with the given uid from
    the network cache, if it exists, otherwise returns None.

    Args:
        itgs (Itgs): the integrations to (re)use
        uid (str): the uid of the transcript to fetch

    Returns:
        bytes, None: The transcript, if it's available,
            otherwise None.
    """
    redis = await itgs.redis()
    return await cast(
        Awaitable[Optional[bytes]], redis.get(f"transcripts:{uid}".encode("utf-8"))
    )


async def write_transcript_to_network_cache(
    itgs: Itgs, uid: str, content: bytes
) -> None:
    """Writes the given serialized transcript to the network cache.

    Args:
        itgs (Itgs): the integrations to (re)use
        uid (str): the uid of the transcript to write
        content (bytes): the serialized transcript to write, as if from
            `transcript.model_dump_json().encode('utf-8')`
    """
    redis = await itgs.redis()
    await redis.set(f"transcripts:{uid}".encode("utf-8"), content)


async def push_transcript_to_all_instances_local_cache(
    itgs: Itgs, uid: str, content: bytes
) -> None:
    """Actively pushes the given serialized transcript to the local cache
    of all instances.

    Args:
        itgs (Itgs): the integrations to (re)use
        uid (str): the uid of the transcript to write
        content (bytes): the serialized transcript to write, as if from
            `transcript.model_dump_json().encode('utf-8')`
    """
    encoded_uid = uid.encode("utf-8")
    message = (
        len(encoded_uid).to_bytes(4, "big", signed=False)
        + encoded_uid
        + len(content).to_bytes(8, "big", signed=False)
        + content
    )

    redis = await itgs.redis()
    await redis.publish(b"ps:transcripts", message)


async def get_transcript_from_source(itgs: Itgs, uid: str) -> Optional[Transcript]:
    """Attempts to fetch the transcript with the given uid from
    the database, if it exists, otherwise returns None.

    Args:
        itgs (Itgs): the integrations to (re)use
        uid (str): the uid of the transcript to fetch

    Returns:
        Transcript, None: The transcript, if it's available,
            otherwise None.
    """
    conn = await itgs.conn()
    cursor = conn.cursor("none")

    response = await cursor.execute(
        """
        SELECT
            transcript_phrases.starts_at,
            transcript_phrases.ends_at,
            transcript_phrases.phrase
        FROM transcripts, transcript_phrases
        WHERE
            transcripts.uid = ?
            AND transcript_phrases.transcript_id = transcripts.id
        ORDER BY
            transcript_phrases.starts_at ASC,
            transcript_phrases.ends_at ASC,
            transcript_phrases.uid ASC
        """,
        (uid,),
    )
    if not response.results:
        return None

    phrases: List[TranscriptPhrase] = []
    for row in response.results:
        phrases.append(
            TranscriptPhrase(
                starts_at=row[0],
                ends_at=row[1],
                phrase=row[2],
            )
        )

    return Transcript(
        uid=uid,
        phrases=phrases,
    )


async def _actively_sync_local_cache():
    assert pps.instance is not None

    async with pps.PPSSubscription(pps.instance, "ps:transcripts", "taslc") as sub:
        async for raw_message in sub:
            message = io.BytesIO(raw_message)
            uid_length = int.from_bytes(message.read(4), "big", signed=False)
            uid = message.read(uid_length).decode("utf-8")
            content_length = int.from_bytes(message.read(8), "big", signed=False)
            content = message.read(content_length)
            async with Itgs() as itgs:
                await write_transcript_to_local_cache(itgs, uid, content)


@lifespan_handler
async def actively_sync_local_cache():
    task = asyncio.create_task(_actively_sync_local_cache())
    yield
