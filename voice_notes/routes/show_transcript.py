import asyncio
import random
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, validator
from typing import Annotated, Literal, Optional
from error_middleware import handle_warning
from lib.journals.data_to_client import (
    DataToClientContext,
    get_journal_chat_job_voice_note_metadata,
)
from models import (
    AUTHORIZATION_UNKNOWN_TOKEN,
    STANDARD_ERRORS_BY_CODE,
    StandardErrorResponse,
)
import voice_notes.auth
import auth
import lib.journals.client_keys
import lib.journals.master_keys
from itgs import Itgs

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
    """Returns the transcript for the given voice note that you have access to. This
    will stall the connection if the voice note transcript is still processing,
    so once the upload finishes this can be immediately called.

    We explicitly return 503s with Retry-Later set if we need the client to back off
    to avoid overloading the server.

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

        ctx = DataToClientContext(
            user_sub=std_auth_result.result.sub,
            has_pro=None,
            memory_cached_journeys=dict(),
            memory_cached_voice_notes=dict(),
        )
        voice_note_metadata_task = asyncio.create_task(
            get_journal_chat_job_voice_note_metadata(
                itgs, ctx=ctx, voice_note_uid=args.voice_note_uid
            )
        )
        try:
            voice_note_metadata = await asyncio.wait_for(
                voice_note_metadata_task, timeout=5
            )
        except asyncio.TimeoutError:
            try:
                await voice_note_metadata_task
            except asyncio.CancelledError:
                current_task = asyncio.current_task()
                if current_task is not None and current_task.cancelling() > 0:
                    raise
            await handle_warning(
                f"{__name__}:timeout",
                f"User `{std_auth_result.result.sub}` had a JWT for access to the voice note "
                f"with uid `{args.voice_note_uid}`, but we could not find the transcript in time",
            )
            return Response(
                status_code=503,
                headers={
                    "Retry-After": str(random.randint(5, 10)),
                },
            )

        if voice_note_metadata is None:
            await handle_warning(
                f"{__name__}:missing_voice_note",
                f"User `{std_auth_result.result.sub}` had a JWT for access to the voice note "
                f"with uid `{args.voice_note_uid}`, but we could not find it",
            )
            return Response(
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="voice_note_not_found",
                    message="The provided voice note was not found. It may have been deleted",
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=404,
            )

        external_transcript = voice_note_metadata.transcript.to_external(uid="")
        encrypted_external_transcript = client_key.journal_client_key.encrypt(
            external_transcript.__pydantic_serializer__.to_json(external_transcript)
        )
        return Response(
            content=VoiceNoteTranscriptionResponse.__pydantic_serializer__.to_json(
                VoiceNoteTranscriptionResponse(
                    voice_note_uid=args.voice_note_uid,
                    journal_client_key_uid=args.journal_client_key_uid,
                    encrypted_transcript=encrypted_external_transcript.decode("ascii"),
                    transcript=None,
                )
            ),
            headers={
                "Content-Type": "application/json; charset=utf-8",
            },
            status_code=200,
        )
