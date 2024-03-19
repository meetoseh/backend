from typing import Annotated, Optional
from fastapi import APIRouter, Header
from models import STANDARD_ERRORS_BY_CODE
from resources.videos.read_thumbnail_images import (
    ReadVideoThumbnailRequest,
    ReadVideoThumbnailResponse,
    read_video_thumbnails,
)


router = APIRouter()


@router.post(
    "/search",
    response_model=ReadVideoThumbnailResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_onboarding_video_thumbnails(
    args: ReadVideoThumbnailRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Lists out onboarding video thumbnails

    This requires standard authorization for a user with admin access
    """
    return await read_video_thumbnails(
        args, authorization=authorization, table_name="onboarding_video_thumbnails"
    )
