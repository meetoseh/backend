import secrets
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, StringConstraints
from typing import Annotated, Literal, Optional
from models import (
    AUTHORIZATION_UNKNOWN_TOKEN,
    STANDARD_ERRORS_BY_CODE,
    StandardErrorResponse,
)
from auth import auth_any
from itgs import Itgs
from loguru import logger
import courses.auth


class AttachCourseRequest(BaseModel):
    course_uid: Annotated[str, StringConstraints(max_length=255, min_length=3)] = Field(
        description="The course uid to attach to the user"
    )
    course_jwt: Annotated[
        str, StringConstraints(min_length=3, max_length=1024 * 16)
    ] = Field(
        description="The JWT that shows you have access to taking classes in the course"
    )


ERROR_409_TYPES = Literal["already_attached"]
ERROR_ALREADY_ATTACHED_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_409_TYPES](
        type="already_attached",
        message="You already have attached that course",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=409,
)

router = APIRouter()


@router.post(
    "/attach_via_jwt",
    status_code=200,
    responses={
        "409": {
            "description": "The user already has the course attached",
            "model": StandardErrorResponse[ERROR_409_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def attach_via_entitlement(
    args: AttachCourseRequest, authorization: Annotated[Optional[str], Header()] = None
):
    """Attaches the given course, provided the JWT allows taking classes in that course

    Requires standard authorization.
    """
    async with Itgs() as itgs:
        std_auth_result = await auth_any(itgs, authorization)
        if std_auth_result.result is None:
            return std_auth_result.error_response

        course_auth_result = await courses.auth.auth_any(
            itgs, f"bearer {args.course_jwt}"
        )
        if course_auth_result.result is None:
            return course_auth_result.error_response

        if (
            course_auth_result.result.course_uid != args.course_uid
            or (
                course_auth_result.result.oseh_flags
                & courses.auth.CourseAccessFlags.TAKE_JOURNEYS
            )
            == 0
        ):
            return AUTHORIZATION_UNKNOWN_TOKEN

        request_id = secrets.token_urlsafe(6)
        logger.debug(
            f"Attaching {args.course_uid=} to {std_auth_result.result.sub=} via JWT; assigned {request_id=}"
        )

        new_course_user_uid = f"oseh_cu_{secrets.token_urlsafe(16)}"
        now = time.time()
        logger.debug(
            f"{request_id=} attaching course user via {new_course_user_uid=} @ {now}"
        )

        conn = await itgs.conn()
        cursor = conn.cursor("strong")
        response = await cursor.executeunified3(
            (
                (
                    "SELECT 1 FROM users WHERE sub=?",
                    (std_auth_result.result.sub,),
                ),
                (
                    "SELECT 1 FROM courses WHERE uid=?",
                    (args.course_uid,),
                ),
                (
                    "SELECT 1 FROM users, courses, course_users WHERE"
                    " users.sub = ?"
                    " AND courses.uid = ?"
                    " AND users.id = course_users.user_id"
                    " AND courses.id = course_users.course_id",
                    (std_auth_result.result.sub, args.course_uid),
                ),
                (
                    "INSERT INTO course_users ("
                    " uid, course_id, user_id, last_priority, last_journey_at, created_at, updated_at"
                    ") SELECT"
                    " ?,"
                    " courses.id,"
                    " users.id,"
                    " NULL,"
                    " NULL,"
                    " ?,"
                    " ? "
                    "FROM users, courses "
                    "WHERE"
                    " users.sub = ?"
                    " AND courses.uid = ?"
                    " AND NOT EXISTS ("
                    "  SELECT 1 FROM course_users AS cu"
                    "  WHERE"
                    "   cu.user_id = users.id"
                    "   AND cu.course_id = courses.id"
                    " )",
                    (
                        new_course_user_uid,
                        now,
                        now,
                        std_auth_result.result.sub,
                        args.course_uid,
                    ),
                ),
            ),
        )

        user_exists_response = response.items[0]
        course_exists_response = response.items[1]
        already_attached_response = response.items[2]
        attach_response = response.items[3]

        attached = (
            attach_response.rows_affected is not None
            and attach_response.rows_affected > 0
        )

        if not user_exists_response.results:
            logger.warning(f"{request_id=} raced user delete")
            assert not attached, response
            return AUTHORIZATION_UNKNOWN_TOKEN

        if not course_exists_response.results:
            logger.warning(f"{request_id=} raced course delete")
            assert not attached, response
            return AUTHORIZATION_UNKNOWN_TOKEN

        if already_attached_response.results:
            logger.warning(f"{request_id=} already attached")
            return ERROR_ALREADY_ATTACHED_RESPONSE

        assert attached, response
        assert attach_response.rows_affected == 1, response
        return Response(status_code=200)
