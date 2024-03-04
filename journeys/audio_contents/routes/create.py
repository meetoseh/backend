import secrets
from typing import Optional
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from auth import auth_admin
from file_uploads.helper import (
    FileUploadWithProgressResponse,
    start_upload,
)
from models import STANDARD_ERRORS_BY_CODE
from itgs import Itgs

router = APIRouter()


class CreateJourneyAudioContentRequest(BaseModel):
    file_size: int = Field(description="The size of the file in bytes", ge=1)


@router.post(
    "/",
    response_model=FileUploadWithProgressResponse,
    responses=STANDARD_ERRORS_BY_CODE,
    status_code=201,
)
async def create_journey_audio_content(
    args: CreateJourneyAudioContentRequest,
    authorization: Optional[str] = Header(None),
):
    """Starts the process to create a new journey audio content. Raw formats are
    suggested, such as 2 channels (stereo) * 44.1 Khz * 24 bits = 2116.8kpbs - the
    file will be compressed at multiple different levels so that it can be played
    on a variety of devices in a variety of network conditions.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        job_progress_uid = f"oseh_jp_{secrets.token_urlsafe(16)}"
        res = await start_upload(
            itgs,
            file_size=args.file_size,
            success_job_name="runners.process_journey_audio_content",
            success_job_kwargs={
                "uploaded_by_user_sub": auth_result.result.sub,
                "job_progress_uid": job_progress_uid,
            },
            failure_job_name="runners.delete_file_upload",
            failure_job_kwargs=dict(),
            job_progress_uid=job_progress_uid,
            expires_in=86400,
        )
        return Response(
            content=res.__pydantic_serializer__.to_json(res),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=201,
        )
