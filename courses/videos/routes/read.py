from typing import Annotated, Optional
from fastapi import APIRouter, Header
from models import STANDARD_ERRORS_BY_CODE
from resources.videos.read import (
    ReadUploadedVideoRequest,
    ReadUploadedVideoResponse,
    read_uploaded_videos,
)


router = APIRouter()


@router.post(
    "/search",
    response_model=ReadUploadedVideoResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_course_videos(
    args: ReadUploadedVideoRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Lists out course videos

    This requires standard authorization for a user with admin access
    """
    return await read_uploaded_videos(
        args, authorization=authorization, table_name="course_videos"
    )
