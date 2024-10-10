import io
import json
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, validator
from typing import Annotated, List, Literal, Optional, cast
from content_files.models import ContentFileRef
from error_middleware import handle_warning
from models import (
    AUTHORIZATION_UNKNOWN_TOKEN,
    STANDARD_ERRORS_BY_CODE,
    StandardErrorResponse,
)
import auth as std_auth
import voice_notes.auth
import content_files.auth
import lib.journals.client_keys
import lib.journals.master_keys
from itgs import Itgs
from dataclasses import dataclass


class ShowVoiceNoteAudioRequest(BaseModel):
    voice_note_uid: str = Field(
        description="The UID of the voice note whose audio you want",
    )
    voice_note_jwt: str = Field(
        description="The JWT that shows you can access the voice note",
    )
    journal_client_key_uid: str = Field(
        description="The UID of the client key to use for encrypting the bins"
    )


class ShowVoiceNoteAudioResponse(BaseModel):
    voice_note_uid: str = Field(
        description="The UID of the voice note whose audio is being returned"
    )
    audio_content_file: ContentFileRef = Field(
        description="Where the underlying audio data can be retrieved"
    )
    duration_seconds: float = Field(description="The duration of the audio in seconds")
    binned_time_vs_intensity: Optional[List[List[float]]] = Field(
        None,
        description="Never set, used for showing the typed version of encrypted_binned_time_vs_intensity in docs",
    )
    encrypted_binned_time_vs_intensity: str = Field(
        description=(
            "The fernet-encrypted time vs intensity graphs in descending order of "
            "number of bins. The values are 0-1, 0 being the quietest and 1 being the loudest"
        )
    )

    @validator("binned_time_vs_intensity")
    def validate_binned_time_vs_intensity(cls, value):
        if value is not None:
            raise ValueError("binned_time_vs_intensity should never be set")
        return value


router = APIRouter()

ERROR_404_TYPES = Literal["voice_note_not_found", "key_unavailable"]
ERROR_VOICE_NOTE_NOT_FOUND_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="voice_note_not_found",
        message="The voice note with the given UID was not found despite valid authorization. It may have been deleted.",
    )
    .model_dump_json()
    .encode("utf-8"),
    status_code=404,
)
ERROR_KEY_UNAVAILABLE_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="key_unavailable",
        message="The client key with the given UID is not acceptable for this transfer. Generate a new one",
    )
    .model_dump_json()
    .encode("utf-8"),
    status_code=404,
)

ERROR_503_TYPES = Literal["voice_note_processing"]
ERROR_VOICE_NOTE_PROCESSING_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_503_TYPES](
        type="voice_note_processing",
        message="The voice note is still being processed. Try again later",
    )
    .model_dump_json()
    .encode("utf-8"),
    status_code=503,
)


@router.post(
    "/show_audio",
    response_model=ShowVoiceNoteAudioResponse,
    responses={
        "404": {
            "model": StandardErrorResponse[ERROR_404_TYPES],
            "description": "The voice note was not found or the client key is not acceptable",
        },
        "503": {
            "model": StandardErrorResponse[ERROR_503_TYPES],
            "description": (
                "The voice note is still processing. This status code can also be "
                "returned with no content or different content for generic 503s and "
                "is always retryable. Check for a retry-after header as a minimum retry delay"
            ),
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def show_voice_note_audio(
    args: ShowVoiceNoteAudioRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Returns the audio data for the voice note with the given uid that you have
    access to via the given JWT. The binned data is sent with a second layer of
    encryption.

    Requires standard authentication to the user who owns the client key and voice
    note.
    """
    async with Itgs() as itgs:
        std_auth_result = await std_auth.auth_any(itgs, authorization)
        if std_auth_result.result is None:
            return std_auth_result.error_response

        voice_note_auth_result = await voice_notes.auth.auth_presigned(
            itgs, authorization=args.voice_note_jwt, prefix=""
        )
        if voice_note_auth_result.result is None:
            return voice_note_auth_result.error_response

        if voice_note_auth_result.result.voice_note_uid != args.voice_note_uid:
            return AUTHORIZATION_UNKNOWN_TOKEN

        client_key = await lib.journals.client_keys.get_journal_client_key(
            itgs,
            user_sub=std_auth_result.result.sub,
            journal_client_key_uid=args.journal_client_key_uid,
            read_consistency="none",
        )
        if client_key.type == "not_found":
            client_key = await lib.journals.client_keys.get_journal_client_key(
                itgs,
                user_sub=std_auth_result.result.sub,
                journal_client_key_uid=args.journal_client_key_uid,
                read_consistency="weak",
            )
        if client_key.type != "success":
            await handle_warning(
                f"{__name__}:client_key:{client_key.type}",
                f"failed to get client key {args.journal_client_key_uid} for user {std_auth_result.result.sub}",
            )
            return ERROR_KEY_UNAVAILABLE_RESPONSE

        db_info = await _get_from_db(
            itgs,
            voice_note_uid=args.voice_note_uid,
            user_sub=std_auth_result.result.sub,
            read_consistency="none",
        )
        if db_info is None:
            redis = await itgs.redis()
            found_in_processing = cast(
                bytes,
                await redis.hget(
                    b"voice_notes:processing:" + args.voice_note_uid.encode("utf-8"),  # type: ignore
                    b"user_sub",  # type: ignore
                ),
            )
            if (
                found_in_processing is not None
                and found_in_processing != std_auth_result.result.sub.encode("utf-8")
            ):
                return ERROR_VOICE_NOTE_NOT_FOUND_RESPONSE
            db_info = await _get_from_db(
                itgs,
                voice_note_uid=args.voice_note_uid,
                user_sub=std_auth_result.result.sub,
                read_consistency="weak",
            )
            if db_info is None:
                return ERROR_VOICE_NOTE_NOT_FOUND_RESPONSE

        master_key = (
            await lib.journals.master_keys.get_journal_master_key_for_decryption(
                itgs,
                user_sub=std_auth_result.result.sub,
                journal_master_key_uid=db_info.user_journal_master_key_uid,
            )
        )
        if master_key.type != "success":
            await handle_warning(
                f"{__name__}:master_key:{master_key.type}",
                f"failed to get master key {db_info.user_journal_master_key_uid} for user {std_auth_result.result.sub}",
            )
            return ERROR_VOICE_NOTE_PROCESSING_RESPONSE

        files = await itgs.files()
        out = io.BytesIO()
        await files.download(
            out, bucket=files.default_bucket, key=db_info.tvi_s3_file_key, sync=True
        )
        decrypted_info = master_key.journal_master_key.decrypt(out.getvalue(), ttl=None)
        if not decrypted_info.startswith(b'{"type": "tvi", "version": 1}\n'):
            await handle_warning(
                f"{__name__}:tvi_header",
                f"bad header for tvi file at {db_info.tvi_s3_file_key} for user {std_auth_result.result.sub}",
            )
            return ERROR_VOICE_NOTE_PROCESSING_RESPONSE

        bins: List[List[float]] = []
        try:
            for idx, line in enumerate(decrypted_info.split(b"\n")):
                if not line:
                    continue
                # skip idx 0 (header), 1 (metadata). keep 2, skip 3 (metadata about 2), keep 3, skip 4 (metadata about 3), etc
                if idx < 2 or (idx % 2) == 1:
                    continue
                parsed_line = json.loads(line)
                assert isinstance(parsed_line, list)
                assert len(parsed_line) > 0
                assert not bins or len(bins[-1]) > len(parsed_line)
                bins.append(parsed_line)
        except BaseException as e:
            await handle_warning(
                f"{__name__}:corrupt_bins",
                f"corrupt bins in tvi file at `{db_info.tvi_s3_file_key}` for user `{std_auth_result.result.sub}`\n\n```\n{decrypted_info.decode('utf-8')}\n```\n",
                exc=e,
            )
            if not bins:
                raise

        dumped_bins = json.dumps(bins)
        reencrypted_bins = client_key.journal_client_key.encrypt(
            dumped_bins.encode("utf-8")
        )
        return Response(
            content=ShowVoiceNoteAudioResponse.__pydantic_serializer__.to_json(
                ShowVoiceNoteAudioResponse(
                    voice_note_uid=args.voice_note_uid,
                    audio_content_file=ContentFileRef(
                        uid=db_info.audio_content_file_uid,
                        jwt=await content_files.auth.create_jwt(
                            itgs, db_info.audio_content_file_uid
                        ),
                    ),
                    duration_seconds=db_info.duration_seconds,
                    binned_time_vs_intensity=None,
                    encrypted_binned_time_vs_intensity=reencrypted_bins.decode("ascii"),
                )
            ),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=200,
        )


@dataclass
class _FromDBResult:
    audio_content_file_uid: str
    """The uid of the content file containing the audio"""
    duration_seconds: float
    """The duration of the audio in seconds"""
    user_journal_master_key_uid: str
    """the uid of the user journal master key encrypting the time vs intensity data"""
    tvi_s3_file_key: str
    """The s3 file containing the time vs intensity data"""


async def _get_from_db(
    itgs: Itgs,
    /,
    *,
    voice_note_uid: str,
    user_sub: str,
    read_consistency: Literal["none", "weak", "strong"],
) -> Optional[_FromDBResult]:
    conn = await itgs.conn()
    cursor = conn.cursor(read_consistency)

    response = await cursor.execute(
        """
SELECT
    content_files.uid,
    content_files.duration_seconds,
    user_journal_master_keys.uid,
    s3_files.key
FROM voice_notes, content_files, user_journal_master_keys, s3_files, users
WHERE
    voice_notes.uid = ?
    AND voice_notes.audio_content_file_id = content_files.id
    AND user_journal_master_keys.id = voice_notes.user_journal_master_key_id
    AND s3_files.id = voice_notes.time_vs_avg_signal_intensity_s3_file_id
    AND voice_notes.user_id = users.id
    AND users.sub = ?
        """,
        (voice_note_uid, user_sub),
    )
    if not response.results:
        return None

    return _FromDBResult(
        audio_content_file_uid=response.results[0][0],
        duration_seconds=response.results[0][1],
        user_journal_master_key_uid=response.results[0][2],
        tvi_s3_file_key=response.results[0][3],
    )
