from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal, Optional
from auth import auth_any
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from file_uploads.helper import FileUploadResponse, start_upload
from itgs import Itgs

router = APIRouter()


class UploadProfilePictureRequest(BaseModel):
    file_size: int = Field(
        description="The size of the file in bytes", ge=1, le=1024 * 1024 * 128
    )


ERROR_429_TYPES = Literal["too_many_requests"]
TOO_MANY_REQUESTS = Response(
    content=StandardErrorResponse[ERROR_429_TYPES](
        type="too_many_requests",
        message="You are doing that too frequently. Try again in a little bit.",
    ).model_dump_json(),
    headers={
        "Content-Type": "application/json; charset=utf-8",
    },
)


@router.post(
    "/profile_picture",
    response_model=FileUploadResponse,
    responses={
        "429": {
            "description": "Too many requests",
            "model": StandardErrorResponse[ERROR_429_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def upload_profile_picture(
    args: UploadProfilePictureRequest,
    authorization: Optional[str] = Header(None),
):
    """Starts the process to upload a new profile picture. Profile pictures are
    cropped to a circle, and at least 512x512 is suggested for maximum support.

    This uses standard authentication and requires the user to be logged in.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        redis = await itgs.redis()
        async with redis.pipeline() as pipe:
            key = f"users:{auth_result.result.sub}:recent_profile_image_uploads".encode(
                "utf-8"
            )
            pipe.multi()
            await pipe.incr(key)
            await pipe.expire(key, 3600, nx=True)
            result = await pipe.execute()

        if result[0] > 10:
            return TOO_MANY_REQUESTS

        res = await start_upload(
            itgs,
            file_size=args.file_size,
            success_job_name="runners.process_uploaded_profile_picture",
            success_job_kwargs={"user_sub": auth_result.result.sub},
            failure_job_name="runners.delete_file_upload",
            failure_job_kwargs=dict(),
        )
        return Response(
            content=res.model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=201,
        )
