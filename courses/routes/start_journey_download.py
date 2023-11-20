import secrets
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal, Optional
from content_files.models import ContentFileRef
from error_middleware import handle_contextless_error
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from auth import auth_any
from itgs import Itgs
import users.lib.entitlements as entitlements
from content_files.auth import create_jwt as create_content_file_jwt
from journeys.lib.notifs import on_entering_lobby

router = APIRouter()


class StartJourneyDownloadRequest(BaseModel):
    journey_uid: str = Field(description="The UID of the journey you want to download")
    course_uid: str = Field(
        description="The UID of the course that you own that includes the journey"
    )


class StartJourneyDownloadResponse(BaseModel):
    audio: ContentFileRef = Field(
        description="The audio content which can be downloaded"
    )
    video: Optional[ContentFileRef] = Field(
        description="The video which can be downloaded, if available"
    )
    last_taken_at: float = Field(
        description="The updated last_taken_at time for the journey"
    )


ERROR_404_TYPES = Literal["journey_not_found"]
JOURNEY_NOT_FOUND_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="journey_not_found",
        message="That journey does not exist, or it is not in that course, or you do not own that course",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
)


@router.post(
    "/start_journey_download",
    response_model=StartJourneyDownloadResponse,
    responses={
        "404": {
            "description": "The journey was not found",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def start_journey_download(
    args: StartJourneyDownloadRequest, authorization: Optional[str] = Header(None)
):
    """Fetches the signed audio and full video for the given journey, assuming that
    you own the course that the journey is in. Note that this does not advance
    the course; it's typically necessary for the client to consider if that
    would be appropriate given the context they are doing this in.

    Requires standard authorization
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor("none")

        response = await cursor.execute(
            "SELECT courses.title, courses.slug, courses.revenue_cat_entitlement FROM courses WHERE uid=?",
            (args.course_uid,),
        )
        if not response.results:
            return JOURNEY_NOT_FOUND_RESPONSE

        course_title: str = response.results[0][0]
        course_slug: str = response.results[0][1]
        revenue_cat_entitlement: str = response.results[0][2]

        entitlement_info = await entitlements.get_entitlement(
            itgs, user_sub=auth_result.result.sub, identifier=revenue_cat_entitlement
        )
        if entitlement_info is None or not entitlement_info.is_active:
            return JOURNEY_NOT_FOUND_RESPONSE

        response = await cursor.execute(
            """
            SELECT
                audio_content_files.uid,
                video_content_files.uid
            FROM journeys
            JOIN content_files AS audio_content_files ON audio_content_files.id = journeys.audio_content_file_id
            LEFT OUTER JOIN content_files AS video_content_files ON video_content_files.id = journeys.video_content_file_id
            WHERE
                journeys.uid = ?
                AND EXISTS (
                    SELECT 1 FROM course_journeys, courses
                    WHERE
                        course_journeys.course_id = courses.id
                        AND courses.uid = ?
                        AND course_journeys.journey_id = journeys.id
                )
            """,
            (args.journey_uid, args.course_uid),
        )
        if not response.results:
            return JOURNEY_NOT_FOUND_RESPONSE

        audio_content_file_uid: str = response.results[0][0]
        video_content_file_uid: Optional[str] = response.results[0][1]

        user_journey_uid = f"oseh_uj_{secrets.token_urlsafe(16)}"
        new_last_taken_at = time.time()
        response = await cursor.execute(
            """
            INSERT INTO user_journeys (
                uid, user_id, journey_id, created_at
            )
            SELECT
                ?, users.id, journeys.id, ?
            FROM users, journeys
            WHERE
                users.sub = ?
                AND journeys.uid = ?
            """,
            (
                user_journey_uid,
                new_last_taken_at,
                auth_result.result.sub,
                args.journey_uid,
            ),
        )
        if response.rows_affected is None or response.rows_affected != 1:
            await handle_contextless_error(
                extra_info=f"failed to store that user {auth_result.result.sub} started journey {args.journey_uid} via download"
            )

        await on_entering_lobby(
            itgs,
            user_sub=auth_result.result.sub,
            journey_uid=args.journey_uid,
            action=f"downloading (via course {course_title} [{course_slug}])",
        )

        return Response(
            content=StartJourneyDownloadResponse(
                audio=ContentFileRef(
                    uid=audio_content_file_uid,
                    jwt=await create_content_file_jwt(
                        itgs, content_file_uid=audio_content_file_uid
                    ),
                ),
                video=(
                    None
                    if video_content_file_uid is None
                    else ContentFileRef(
                        uid=video_content_file_uid,
                        jwt=await create_content_file_jwt(
                            itgs, content_file_uid=video_content_file_uid
                        ),
                    )
                ),
                last_taken_at=new_last_taken_at,
            ).model_dump_json(),
            headers={
                "Content-Type": "application/json; charset=utf-8",
            },
        )
