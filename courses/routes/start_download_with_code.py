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
from lib.shared.clean_for_slack import clean_for_non_code_slack, clean_for_slack
from lib.shared.describe_user import enqueue_send_described_user_slack_message
from models import StandardErrorResponse
import socket
import pytz
import datetime


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
        visitor_uid: Optional[str] = response.results[0][4]
        code_created_at_raw: float = response.results[0][5]

        code_created_at_pretty = (
            datetime.datetime.utcfromtimestamp(code_created_at_raw)
            .replace(tzinfo=pytz.utc)
            .astimezone(pytz.timezone("America/Los_Angeles"))
            .strftime("%a %b %d %Y, %I:%M%p")
        )

        msg = (
            f"requested download for {clean_for_non_code_slack(course_title)} "
            f"(`{clean_for_slack(course_slug)}`) via code `{clean_for_slack(args.code)}` "
            f"created {clean_for_non_code_slack(code_created_at_pretty)}"
        )

        if user_sub is not None:
            await enqueue_send_described_user_slack_message(
                itgs,
                message=f"{{name}} {msg}",
                sub=user_sub,
                channel="oseh_bot"
                if os.environ["ENVIRONMENT"] != "dev"
                else "web_error",
            )
        else:
            slack = await itgs.slack()
            if visitor_uid is not None:
                msg = f"{socket.gethostname()} visitor `{clean_for_slack(visitor_uid)}` {msg}"
            else:
                msg = f"{socket.gethostname()} client with no useful identifiers {msg}"

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
