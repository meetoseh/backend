from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, validator
from typing import Annotated, Literal, Optional
from error_middleware import handle_warning
from models import (
    AUTHORIZATION_UNKNOWN_TOKEN,
    STANDARD_ERRORS_BY_CODE,
    StandardErrorResponse,
)
from temp_files import temp_file
import voice_notes.auth
import auth
import lib.journals.client_keys
import lib.journals.master_keys
from itgs import Itgs
from dataclasses import dataclass

import transcripts.routes.show
import lib.transcripts.model


router = APIRouter()


class VoiceNoteTranscriptionRequest(BaseModel):
    voice_note_uid: str = Field(
        description="The UID of the voice note whose transcript you want",
    )
    voice_note_jwt: str = Field(
        description="The JWT that shows you can access the voice note",
    )
    journal_client_key_uid: str = Field(
        description="The journal client key uid to use as a second encryption layer"
    )


class VoiceNoteTranscriptionResponse(BaseModel):
    voice_note_uid: str = Field(
        description="The UID of the voice note whose transcript is being returned"
    )
    journal_client_key_uid: str = Field(
        description="The UID of the journal client key that was used to encrypt the transcript"
    )
    encrypted_transcript: str = Field(
        description="the fernet-encrypted Transcript object with the uid set to an empty string"
    )
    transcript: Optional[transcripts.routes.show.Transcript] = Field(
        None, description="Never set, used to show the format of the Transcript in docs"
    )

    @validator("transcript")
    def validate_transcript(cls, value):
        if value is not None:
            raise ValueError("transcript should never be set")
        return value


ERROR_404_TYPES = Literal["key_unavailable", "voice_note_not_found"]


@router.post(
    "/show_transcript",
    response_model=VoiceNoteTranscriptionResponse,
    responses={
        "404": {
            "description": "Either the journal client key is not acceptable or the voice note was deleted",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def show_voice_note_transcript(
    args: VoiceNoteTranscriptionRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Returns the double-encrypted transcript for the given voice note that you have
    access to. The first layer of encryption is TLS, the second layer is a journal client
    key (see [POST /api/1/journals/client_keys/](#/journals/create_journal_client_key_api_1_journals_client_keys__post))

    TLS prevents unexpected middle-men, whereas the journal client key prevents
    most enterprise MITM that were purposely installed from passively inspecting
    what the user said. Note that we purposely don't fully break enterprise TLS
    terminators via e.g. pinned client certificates, which would likely prevent
    Oseh from being usable at all in such situations. Instead, we just hide the
    most sensitive, least useful (for malware detection) information from
    accidentally being logged.

    Requires standard authorization plus the voice note JWT.
    """
    async with Itgs() as itgs:
        voice_note_auth_result = await voice_notes.auth.auth_presigned(
            itgs, args.voice_note_jwt, prefix=""
        )
        if voice_note_auth_result.result is None:
            return voice_note_auth_result.error_response

        if voice_note_auth_result.result.voice_note_uid != args.voice_note_uid:
            return AUTHORIZATION_UNKNOWN_TOKEN

        std_auth_result = await auth.auth_any(itgs, authorization)
        if std_auth_result.result is None:
            return std_auth_result.error_response

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
                f"{__name__}:missing_journal_client_key",
                f"User {std_auth_result.result.sub} tried to use a journal client key, but we "
                f"could not retrieve it: {client_key.type}",
            )
            return Response(
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="key_unavailable",
                    message="The provided journal client key is not available or is not acceptable for this transfer. Generate a new one.",
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=404,
            )

        voice_note_info = await _get_voice_note_info(
            itgs,
            voice_note_uid=args.voice_note_uid,
            user_sub=std_auth_result.result.sub,
            read_consistency="none",
        )
        if voice_note_info is None:
            voice_note_info = await _get_voice_note_info(
                itgs,
                voice_note_uid=args.voice_note_uid,
                user_sub=std_auth_result.result.sub,
                read_consistency="weak",
            )
        if voice_note_info is None:
            await handle_warning(
                f"{__name__}:missing_voice_note",
                f"User `{std_auth_result.result.sub}` had a JWT for access to the voice note "
                f"with uid `{args.voice_note_uid}`, but we could not find it (tried @ weak)",
            )
            return Response(
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="voice_note_not_found",
                    message="The provided voice note was not found. It may have been deleted",
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=404,
            )

        master_key = (
            await lib.journals.master_keys.get_journal_master_key_for_decryption(
                itgs,
                user_sub=std_auth_result.result.sub,
                journal_master_key_uid=voice_note_info.user_journal_master_key_uid,
            )
        )
        if master_key.type != "success":
            await handle_warning(
                f"{__name__}:missing_journal_master_key",
                f"User {std_auth_result.result.sub} tried to decrypt a voice note, but we "
                f"could not retrieve the journal master key: {master_key.type}",
            )
            return Response(
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="voice_note_not_found",
                    message="The voice note exists but we were not able to access the transcript",
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=404,
            )

        files = await itgs.files()
        with temp_file(".vtt.fernet") as encrypted_vtt_path:
            try:
                with open(encrypted_vtt_path, "wb") as f:
                    await files.download(
                        f,
                        bucket=files.default_bucket,
                        key=voice_note_info.transcript_s3_file_key,
                        sync=True,
                    )
            except Exception as e:
                await handle_warning(
                    f"{__name__}:download_failure",
                    f"User `{std_auth_result.result.sub}` tried to download a voice note transcript "
                    f"`{args.voice_note_uid}`, which should be at `{voice_note_info.transcript_s3_file_key}`, "
                    f"but we could not download it",
                    exc=e,
                )
                return Response(status_code=500)

            with open(encrypted_vtt_path, "rb") as f:
                encrypted_vtt = f.read()

            vtt_bytes = master_key.journal_master_key.decrypt(encrypted_vtt, ttl=None)
            vtt = vtt_bytes.decode("utf-8")
            internal_transcript = lib.transcripts.model.parse_vtt_transcript(vtt)
            external_transcript = transcripts.routes.show.Transcript(
                uid="",
                phrases=[
                    transcripts.routes.show.TranscriptPhrase(
                        starts_at=tr.start.in_seconds(),
                        ends_at=tr.end.in_seconds(),
                        phrase=text,
                    )
                    for (tr, text) in internal_transcript.phrases
                ],
            )
            encrypted_external_transcript = client_key.journal_client_key.encrypt(
                external_transcript.__pydantic_serializer__.to_json(external_transcript)
            )
            return Response(
                content=VoiceNoteTranscriptionResponse.__pydantic_serializer__.to_json(
                    VoiceNoteTranscriptionResponse(
                        voice_note_uid=args.voice_note_uid,
                        journal_client_key_uid=args.journal_client_key_uid,
                        encrypted_transcript=encrypted_external_transcript.decode(
                            "ascii"
                        ),
                        transcript=None,
                    )
                ),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                },
                status_code=200,
            )


@dataclass
class _VoiceNoteInfo:
    user_journal_master_key_uid: str
    transcript_s3_file_key: str


async def _get_voice_note_info(
    itgs: Itgs,
    /,
    *,
    voice_note_uid: str,
    user_sub: str,
    read_consistency: Literal["none", "weak", "strong"],
) -> Optional[_VoiceNoteInfo]:
    conn = await itgs.conn()
    cursor = conn.cursor(read_consistency)

    response = await cursor.execute(
        """
SELECT
    user_journal_master_keys.uid,
    s3_files.key
FROM voice_notes, user_journal_master_keys, s3_files
WHERE
    voice_notes.uid = ?
    AND user_journal_master_keys.id = voice_notes.user_journal_master_key_id
    AND s3_files.id = voice_notes.transcript_s3_file_id
    AND voice_notes.user_id = (SELECT users.id FROM users WHERE users.sub = ?)
    AND user_journal_master_keys.user_id = voice_notes.user_id
        """,
        (
            voice_note_uid,
            user_sub,
        ),
    )
    if not response.results:
        return None

    return _VoiceNoteInfo(
        user_journal_master_key_uid=response.results[0][0],
        transcript_s3_file_key=response.results[0][1],
    )
