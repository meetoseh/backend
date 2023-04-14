import asyncio
import os
import time
from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal, Optional
from courses.models.course_ref import CourseRef
from courses.auth import create_jwt as create_course_jwt
from itgs import Itgs
from models import StandardErrorResponse
import socket


router = APIRouter()


class StartCourseDownloadWithCodeRequest(BaseModel):
    code: str = Field(description="The code for the download to start")


ERROR_403_TYPES = Literal["invalid"]
AUTHORIZATION_UNKNOWN_CODE = Response(
    content=StandardErrorResponse[ERROR_403_TYPES](
        type="invalid",
        message="The provided code is invalid",
    ).json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=403,
)


@router.post(
    "/start_download_with_code",
    status_code=200,
    response_model=CourseRef,
    responses={
        "403": {
            "description": "The code is invalid",
            "model": StandardErrorResponse[ERROR_403_TYPES],
        }
    },
)
async def start_course_download_with_code(args: StartCourseDownloadWithCodeRequest):
    """Returns the necessary information to download the latest course export
    for the course authorized by the given code, if such a course exists and the
    code is valid.

    To use a users entitlement instead to start the download, use start_course_download
    """
    async with Itgs() as itgs:
        conn = await itgs.conn()
        cursor = conn.cursor("none")

        started_at = time.time()
        response = await cursor.execute(
            """
            SELECT
                courses.uid,
                courses.title,
                courses.slug,
                users.sub,
                users.email,
                visitors.uid,
                course_download_links.created_at
            FROM course_download_links, courses
            LEFT OUTER JOIN users ON users.id = course_download_links.user_id
            LEFT OUTER JOIN visitors ON visitors.id = course_download_links.visitor_id
            WHERE
                course_download_links.course_id = courses.id
                AND course_download_links.code = ?
            """,
            (args.code,),
        )
        if not response.results:
            # because we used a btree to look the code up, we're susceptible to timing attacks
            # to mitigate this, we coarsen the time taken to the nearest 0.5s
            time_taken = time.time() - started_at
            await asyncio.sleep(0.5 - (time_taken % 0.5))
            return AUTHORIZATION_UNKNOWN_CODE

        course_uid: str = response.results[0][0]
        course_title: str = response.results[0][1]
        course_slug: str = response.results[0][2]
        user_sub: Optional[str] = response.results[0][3]
        user_email: Optional[str] = response.results[0][4]
        visitor_uid: Optional[str] = response.results[0][5]
        code_created_at: str = response.results[0][6]

        slack = await itgs.slack()
        identifier = (
            f"{user_email} ({user_sub})"
            if user_email is not None
            else (
                f"{visitor_uid=}"
                if visitor_uid is not None
                else "(no useful identifiers)"
            )
        )
        msg = (
            f"{socket.gethostname()} {identifier} requested download "
            f"for {course_title} ({course_slug}) via code {args.code} "
            f"created at {code_created_at}"
        )
        if os.environ["ENVIRONMENT"] == "dev":
            await slack.send_web_error_message(msg)
        else:
            await slack.send_oseh_bot_message(msg)
        course_jwt = await create_course_jwt(itgs, course_uid=course_uid, duration=60)
        return Response(
            content=CourseRef(uid=course_uid, jwt=course_jwt).json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=200,
        )
