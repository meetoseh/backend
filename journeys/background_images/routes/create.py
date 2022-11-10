from typing import Optional
from fastapi import APIRouter, Header
from pydantic import BaseModel, Field
from auth import auth_admin
from file_uploads.helper import FileUploadResponse, start_upload
from models import STANDARD_ERRORS_BY_CODE
from itgs import Itgs

router = APIRouter()


class CreateJourneyBackgroundImageRequest(BaseModel):
    file_size: int = Field(description="The size of the file in bytes", ge=1)


@router.post("/", response_model=FileUploadResponse, responses=STANDARD_ERRORS_BY_CODE)
async def create_journey_background_image(
    args: CreateJourneyBackgroundImageRequest,
    authorization: Optional[str] = Header(None),
):
    """Starts the process to create a new journey background image. Background images
    are cropped to the center, and at least 1920x1080 is suggested for maximum support.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        return await start_upload(
            itgs,
            file_size=args.file_size,
            success_job_name="runners.process_journey_background_image",
            success_job_kwargs={"uploaded_by_user_sub": auth_result.result.sub},
            failure_job_name="runners.delete_file_upload",
            failure_job_kwargs=dict(),
        )
