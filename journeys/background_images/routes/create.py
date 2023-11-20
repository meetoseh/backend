from typing import Optional
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from auth import auth_admin
from file_uploads.helper import FileUploadResponse, start_upload
from models import STANDARD_ERRORS_BY_CODE
from itgs import Itgs

router = APIRouter()


class CreateJourneyBackgroundImageRequest(BaseModel):
    file_size: int = Field(description="The size of the file in bytes", ge=1)


@router.post(
    "/",
    response_model=FileUploadResponse,
    responses=STANDARD_ERRORS_BY_CODE,
    status_code=201,
)
async def create_journey_background_image(
    args: CreateJourneyBackgroundImageRequest,
    authorization: Optional[str] = Header(None),
):
    """Starts the process to create a new journey background image. Background images
    are cropped to the center, and at least 1920x1920 is suggested for maximum support;
    1920x1080 for desktop, 1080x1920 for instagram

    See [file_uploads](#/file_uploads) for more information on the file upload process.

    This uses standard authentication and requires the user to be an admin.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        res = await start_upload(
            itgs,
            file_size=args.file_size,
            success_job_name="runners.process_journey_background_image",
            success_job_kwargs={"uploaded_by_user_sub": auth_result.result.sub},
            failure_job_name="runners.delete_file_upload",
            failure_job_kwargs=dict(),
        )
        return Response(
            content=res.model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=201,
        )
