import secrets
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Annotated, Optional
from auth import auth_admin

from file_uploads.helper import FileUploadWithProgressResponse, start_upload
from itgs import Itgs
from models import STANDARD_ERRORS_BY_CODE


class Size(BaseModel):
    width: int = Field(description="The width embedded into the template, in pixels")
    height: int = Field(description="The height embedded into the template, in pixels")


class CreateClientFlowImageRequest(BaseModel):
    file_size: int = Field(description="The size of the file in bytes")
    size: Size = Field(
        description=(
            "The size that will be embedded into the image template. When targetting "
            "a field of type string, format `x-image`, there will be an `x-size` property "
            "that provides this value."
        ),
    )


router = APIRouter()


@router.post(
    "/",
    response_model=FileUploadWithProgressResponse,
    responses=STANDARD_ERRORS_BY_CODE,
    status_code=201,
)
async def create_client_flow_image(
    args: CreateClientFlowImageRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Begins the file upload process for an image that will be embedded into
    the email with the given size in CSS pixels.

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        job_progress_uid = f"oseh_jp_{secrets.token_urlsafe(16)}"
        res = await start_upload(
            itgs,
            file_size=args.file_size,
            success_job_name="runners.emails.process_image",
            success_job_kwargs={
                "uploaded_by_user_sub": auth_result.result.sub,
                "job_progress_uid": job_progress_uid,
                "size": args.size.model_dump(),
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
