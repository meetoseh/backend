import json
import secrets
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Annotated, Literal, Optional
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from auth import auth_admin
from itgs import Itgs
import time

from onboarding.videos.lib.internal_onboarding_video import (
    STANDARD_INTERNAL_ONBOARDING_VIDEO_ROW_SELECT_JOIN,
    InternalOnboardingVideo,
    InternalOnboardingVideoRow,
    OnboardingVideoPurpose,
    parse_internal_onboarding_video_row,
)


class CreateOnboardingVideoRequest(BaseModel):
    purpose: OnboardingVideoPurpose = Field(description="The purpose for the video")
    upload_uid: str = Field(description="The uid of the onboarding video upload to use")
    thumbnail_uid: str = Field(
        description="The uid of the onboarding video thumbnail to use"
    )


ERROR_404_TYPES = Literal["upload_not_found", "thumbnail_not_found"]
ERROR_UPLOAD_NOT_FOUND_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="upload_not_found",
        message="There is no onboarding video upload with the given uid "
        + "(did you pass a content file uid instead of the association uid?)",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=404,
)
ERROR_THUMBNAIL_NOT_FOUND_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="thumbnail_not_found",
        message="There is no onboarding video thumbnail with the given uid"
        + "(did you pass an image file uid instead of the association uid?)",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=404,
)

ERROR_409_TYPES = Literal["duplicate"]
ERROR_DUPLICATE_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_409_TYPES](
        type="duplicate",
        message="This content file is already an onboarding video for this purpose",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=409,
)

router = APIRouter()


@router.post(
    "/",
    status_code=201,
    response_model=InternalOnboardingVideo,
    responses={
        "404": {
            "description": "The required upload or thumbnail was not found",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        "409": {
            "description": "The upload is already an onboarding video for this purpose",
            "model": StandardErrorResponse[ERROR_409_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def create_onboarding_video(
    args: CreateOnboardingVideoRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Creates a new onboarding video using the given onboarding video upload and
    thumbnail. It is initialized as visible in admin but inactive.

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor("strong")

        ser_purpose = json.dumps(
            args.purpose.model_dump(), sort_keys=True, separators=(",", ":")
        )
        new_onboarding_video_uid = f"oseh_ov_{secrets.token_urlsafe(16)}"

        response = await cursor.executeunified3(
            (
                (
                    "SELECT 1 FROM onboarding_video_uploads WHERE uid=?",
                    (args.upload_uid,),
                ),
                (
                    "SELECT 1 FROM onboarding_video_thumbnails WHERE uid=?",
                    (args.thumbnail_uid,),
                ),
                (
                    """
SELECT
    1
FROM onboarding_video_uploads, onboarding_videos
WHERE
    onboarding_video_uploads.uid = ?
    AND onboarding_video_uploads.content_file_id = onboarding_videos.video_content_file_id
    AND onboarding_videos.purpose = ?
                    """,
                    (args.upload_uid, ser_purpose),
                ),
                (
                    """
INSERT INTO onboarding_videos (
    uid,
    purpose,
    video_content_file_id,
    thumbnail_image_file_id,
    active_at,
    visible_in_admin,
    created_at
)
SELECT
    ?,
    ?,
    onboarding_video_uploads.content_file_id,
    onboarding_video_thumbnails.image_file_id,
    NULL,
    1,
    ?
FROM onboarding_video_uploads, onboarding_video_thumbnails
WHERE
    onboarding_video_uploads.uid = ?
    AND onboarding_video_thumbnails.uid = ?
    AND NOT EXISTS (
        SELECT 1 FROM onboarding_videos AS ov
        WHERE
            ov.video_content_file_id = onboarding_video_uploads.content_file_id
            AND ov.purpose = ?
    )
                    """,
                    (
                        new_onboarding_video_uid,
                        ser_purpose,
                        time.time(),
                        args.upload_uid,
                        args.thumbnail_uid,
                        ser_purpose,
                    ),
                ),
                (
                    f"{STANDARD_INTERNAL_ONBOARDING_VIDEO_ROW_SELECT_JOIN} WHERE onboarding_videos.uid = ?",
                    (new_onboarding_video_uid,),
                ),
            ),
        )

        upload_exists_response = response[0]
        thumbnail_exists_response = response[1]
        duplicate_response = response[2]
        insert_response = response[3]
        select_response = response[4]

        inserted = (
            insert_response.rows_affected is not None
            and insert_response.rows_affected > 0
        )

        if not upload_exists_response.results:
            assert not inserted, response
            assert not select_response.results, response
            return ERROR_UPLOAD_NOT_FOUND_RESPONSE

        if not thumbnail_exists_response.results:
            assert not inserted, response
            assert not select_response.results, response
            return ERROR_THUMBNAIL_NOT_FOUND_RESPONSE

        if duplicate_response.results:
            assert not inserted, response
            assert not select_response.results, response
            return ERROR_DUPLICATE_RESPONSE

        assert inserted, response
        assert select_response.results, response
        created = await parse_internal_onboarding_video_row(
            itgs, row=InternalOnboardingVideoRow(*select_response.results[0])
        )
        return Response(
            content=created.__pydantic_serializer__.to_json(created),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=201,
        )
