import secrets
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Annotated, Optional
from auth import auth_admin
from file_uploads.helper import FileUploadWithProgressResponse, start_upload
from itgs import Itgs
from models import STANDARD_ERRORS_BY_CODE


router = APIRouter()


class CreateHomeScreenImageRequest(BaseModel):
    file_size: int = Field(description="The size of the file in bytes")


@router.post(
    "/",
    response_model=FileUploadWithProgressResponse,
    responses=STANDARD_ERRORS_BY_CODE,
    status_code=201,
)
async def create_home_screen_image(
    args: CreateHomeScreenImageRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Starts the process to create a new home screen image. The image will be initialized
    such that it is only visible in the admin area, and must be patched to actually be served.

    The top resolution is full width x 350, so this requires at least 3840x1050
    (3x on mobile, 2x on desktop)

    See [file_uploads](#/file_uploads) for more information on the file upload process.

    This uses standard authentication and requires the user to be an admin.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        job_progress_uid = f"oseh_jp_{secrets.token_urlsafe(16)}"
        res = await start_upload(
            itgs,
            file_size=args.file_size,
            success_job_name="runners.process_home_screen_image",
            success_job_kwargs={
                "uploaded_by_user_sub": auth_result.result.sub,
                "job_progress_uid": job_progress_uid,
            },
            failure_job_name="runners.delete_file_upload",
            failure_job_kwargs=dict(),
            job_progress_uid=job_progress_uid,
        )
        return Response(
            content=res.__pydantic_serializer__.to_json(res),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=201,
        )
