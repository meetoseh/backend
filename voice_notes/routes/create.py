import secrets
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Annotated, Optional, cast
import auth
import voice_notes.auth
from file_uploads.helper import FileUploadWithProgressResponse, start_upload
from itgs import Itgs
from models import STANDARD_ERRORS_BY_CODE


router = APIRouter()


class CreateVoiceNoteRequest(BaseModel):
    file_size: int = Field(description="The size of the file in bytes")


class VoiceNoteRef(BaseModel):
    uid: str = Field(description="The UID of the voice note")
    jwt: str = Field(
        description="A token which provides access to the voice note with the given uid"
    )


class CreateVoiceNoteResponse(BaseModel):
    voice_note: VoiceNoteRef = Field(
        description=(
            "The voice note that was created. Note that the voice note cannot be accessed "
            "the upload finishes and the job completes normally, though the client can often monitor "
            "this in the background."
        )
    )
    file_upload: FileUploadWithProgressResponse = Field(
        description="The file upload that was created to store the voice note"
    )


@router.post(
    "/",
    response_model=CreateVoiceNoteResponse,
    responses=STANDARD_ERRORS_BY_CODE,
    status_code=201,
)
async def create_voice_note(
    args: CreateVoiceNoteRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Starts the process to create a new voice note for the authorized user. When the upload
    finishes

    See [file_uploads](#/file_uploads) for more information on the file upload process.

    This uses standard authentication.
    """
    async with Itgs() as itgs:
        auth_result = await auth.auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        job_progress_uid = f"oseh_jp_{secrets.token_urlsafe(16)}"
        voice_note_uid = f"oseh_vn_{secrets.token_urlsafe(16)}"

        voice_note_uid_bytes = voice_note_uid.encode("ascii")

        started_at_bytes = str(int(time.time())).encode("ascii")

        redis = await itgs.redis()
        async with redis.pipeline() as pipe:
            pipe.multi()
            await pipe.zadd(  # type: ignore
                b"voice_notes:processing",
                mapping={voice_note_uid_bytes: started_at_bytes},
            )
            await pipe.hset(  # type: ignore
                b"voice_notes:processing:" + voice_note_uid_bytes,  # type: ignore
                mapping={
                    b"uid": voice_note_uid_bytes,
                    b"job_progress_uid": job_progress_uid.encode("ascii"),
                    b"user_sub": auth_result.result.sub.encode("utf-8"),
                    b"started_at": started_at_bytes,
                    b"upload_success_job_at": b"not_yet",
                    b"stitched_s3_key": b"not_yet",
                    b"journal_master_key_uid": b"not_yet",
                    b"transcribe_job_queued_at": b"not_yet",
                    b"encrypted_transcription_vtt": b"not_yet",
                    b"transcription_source": b"not_yet",
                    b"transcribe_job_finished_at": b"not_yet",
                    b"transcode_job_queued_at": b"not_yet",
                    b"transcode_content_file_uid": b"not_yet",
                    b"transcode_job_finished_at": b"not_yet",
                    b"analyze_job_queued_at": b"not_yet",
                    b"encrypted_time_vs_intensity": b"not_yet",
                    b"analyze_job_finished_at": b"not_yet",
                    b"finalize_job_queued_at": b"not_yet",
                },
            )
            await pipe.execute()

        file_res = await start_upload(
            itgs,
            file_size=args.file_size,
            success_job_name="runners.voice_notes.process",
            success_job_kwargs={
                "uploaded_by_user_sub": auth_result.result.sub,
                "job_progress_uid": job_progress_uid,
                "voice_note_uid": voice_note_uid,
            },
            failure_job_name="runners.delete_file_upload",
            failure_job_kwargs={},
            job_progress_uid=job_progress_uid,
        )

        voice_note_jwt = await voice_notes.auth.create_jwt(
            itgs, voice_note_uid=voice_note_uid
        )

        res = CreateVoiceNoteResponse(
            voice_note=VoiceNoteRef(uid=voice_note_uid, jwt=voice_note_jwt),
            file_upload=cast(FileUploadWithProgressResponse, file_res),
        )

        return Response(
            content=res.__pydantic_serializer__.to_json(res),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=201,
        )
