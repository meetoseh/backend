import os
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Optional
from courses.models.course_ref import CourseRef
from courses.auth import create_jwt as create_course_jwt
from auth import auth_any
from itgs import Itgs
from models import STANDARD_ERRORS_BY_CODE, AUTHORIZATION_UNKNOWN_TOKEN
import users.lib.entitlements
import socket


router = APIRouter()


class StartCourseDownloadRequest(BaseModel):
    course_uid: str = Field(
        description=("The course whose export to start the download for")
    )


@router.post(
    "/start_download",
    status_code=200,
    response_model=CourseRef,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def start_course_download(
    args: StartCourseDownloadRequest, authorization: Optional[str] = Header(None)
):
    """Returns the necessary information to download the latest course export
    for the course with the given uid, if such a course exists and the user is
    entitled to it.

    To use a code instead to start the download, use start_course_download_with_code

    Requires standard authorization to a user with access to the course with that uid.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor("none")

        response = await cursor.execute(
            "SELECT title, slug, revenue_cat_entitlement FROM courses WHERE uid = ?",
            (args.course_uid,),
        )
        if not response.results:
            return AUTHORIZATION_UNKNOWN_TOKEN

        course_title: str = response.results[0][0]
        course_slug: str = response.results[0][1]
        entitlement_iden: str = response.results[0][2]
        entitlement = await users.lib.entitlements.get_entitlement(
            itgs, user_sub=auth_result.result.sub, identifier=entitlement_iden
        )
        if not entitlement.is_active:
            return AUTHORIZATION_UNKNOWN_TOKEN

        slack = await itgs.slack()
        identifier = (
            f"{auth_result.result.claims['name']} ({auth_result.result.claims['email']})"
            if auth_result.result.claims is not None
            and "name" in auth_result.result.claims
            and "email" in auth_result.result.claims
            else auth_result.result.sub
        )
        msg = f"{socket.gethostname()} {identifier} requested download for {course_title} ({course_slug})"

        if os.environ["ENVIRONMENT"] == "dev":
            await slack.send_web_error_message(msg)
        else:
            await slack.send_oseh_bot_message(msg)
        course_jwt = await create_course_jwt(
            itgs, course_uid=args.course_uid, duration=60
        )
        return Response(
            content=CourseRef(uid=args.course_uid, jwt=course_jwt).json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=200,
        )
