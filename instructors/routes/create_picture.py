from typing import Optional
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from auth import auth_admin
from file_uploads.helper import FileUploadResponse, start_upload
from models import STANDARD_ERRORS_BY_CODE
from itgs import Itgs

router = APIRouter()


class CreateInstructorProfilePictureRequest(BaseModel):
    uid: str = Field(
        description=(
            "The UID of the instructor to attach the profile picture to, if "
            "and when the image is successfully uploaded and processed"
        )
    )

    file_size: int = Field(description="The size of the file in bytes", ge=1)


@router.post(
    "/pictures/",
    response_model=FileUploadResponse,
    responses=STANDARD_ERRORS_BY_CODE,
    status_code=201,
)
async def create_instructor_profile_picture(
    args: CreateInstructorProfilePictureRequest,
    authorization: Optional[str] = Header(None),
):
    """Starts the process to create a new instructor profile picture. These
    pictures are cropped to the center, are exported square, and at least
    512x512 is suggested for maximum support. The instructor image is attached
    to the instructor with the given UID, if and when the image is successfully
    uploaded and processed.

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
            success_job_name="runners.process_instructor_profile_picture",
            success_job_kwargs={
                "uploaded_by_user_sub": auth_result.result.sub,
                "instructor_uid": args.uid,
            },
            failure_job_name="runners.delete_file_upload",
            failure_job_kwargs=dict(),
        )
        return Response(
            content=res.model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=201,
        )
