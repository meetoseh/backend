import secrets
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Annotated, Literal, Optional
from models import (
    AUTHORIZATION_UNKNOWN_TOKEN,
    STANDARD_ERRORS_BY_CODE,
    StandardErrorResponse,
)
from itgs import Itgs
import auth as std_auth
import courses.auth as courses_auth


router = APIRouter()


class LikeCourseRequest(BaseModel):
    uid: str = Field(description="The unique identifier for the course to like")
    jwt: str = Field(description="A JWT for that course with at least the LIKE flag")


class LikeCourseResponse(BaseModel):
    liked_at: float = Field(
        description="When the course was liked, in seconds since the epoch"
    )


ERROR_404_TYPES = Literal["course_not_found"]
COURSE_NOT_FOUND_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="course_not_found",
        message="There is no course with that uid",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=404,
)

ERROR_409_TYPES = Literal["already_liked"]
ALREADY_LIKED_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_409_TYPES](
        type="already_liked",
        message="The user has already liked this course",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=409,
)


@router.post(
    "/courses/likes",
    status_code=201,
    response_model=LikeCourseResponse,
    responses={
        "404": {
            "description": "There is no course with that uid",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        "409": {
            "description": "The user has already liked this course",
            "model": StandardErrorResponse[ERROR_409_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def like_course(
    args: LikeCourseRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Likes the course with the given uid, if it has not already been liked.

    Requires standard authorization in the header and the course jwt in the body
    with the LIKE flag set.
    """
    request_at = time.time()

    async with Itgs() as itgs:
        std_auth_result = await std_auth.auth_any(itgs, authorization)
        if std_auth_result.result is None:
            return std_auth_result.error_response

        course_auth_result = await courses_auth.auth_any(itgs, f"bearer {args.jwt}")
        if course_auth_result.result is None:
            return course_auth_result.error_response

        if (
            course_auth_result.result.course_uid != args.uid
            or (
                course_auth_result.result.oseh_flags
                & courses_auth.CourseAccessFlags.LIKE
            )
            == 0
        ):
            return AUTHORIZATION_UNKNOWN_TOKEN

        conn = await itgs.conn()
        cursor = conn.cursor("strong")

        new_like_uid = f"oseh_ucl_{secrets.token_urlsafe(16)}"
        response = await cursor.executeunified3(
            (
                ("SELECT 1 FROM courses WHERE uid = ?", (args.uid,)),
                ("SELECT 1 FROM users WHERE sub = ?", (std_auth_result.result.sub,)),
                (
                    "SELECT 1 FROM user_course_likes, users, courses "
                    "WHERE"
                    " user_course_likes.user_id = users.id"
                    " AND user_course_likes.course_id = courses.id"
                    " AND users.sub = ?"
                    " AND courses.uid = ?",
                    (std_auth_result.result.sub, args.uid),
                ),
                (
                    "INSERT INTO user_course_likes ("
                    " uid, user_id, course_id, created_at"
                    ") SELECT"
                    " ?, users.id, courses.id, ? "
                    "FROM users, courses "
                    "WHERE"
                    " users.sub = ?"
                    " AND courses.uid = ?"
                    " AND NOT EXISTS ("
                    "  SELECT 1 FROM user_course_likes AS ucl"
                    "  WHERE ucl.user_id = users.id"
                    "  AND ucl.course_id = courses.id"
                    " )",
                    (
                        new_like_uid,
                        request_at,
                        std_auth_result.result.sub,
                        args.uid,
                    ),
                ),
            )
        )

        course_exists_response = response.items[0]
        user_exists_response = response.items[1]
        already_liked_response = response.items[2]
        insert_like_response = response.items[3]

        inserted = (
            insert_like_response.rows_affected is not None
            and insert_like_response.rows_affected > 0
        )
        if not course_exists_response.results:
            assert not inserted, response
            return COURSE_NOT_FOUND_RESPONSE

        if not user_exists_response.results:
            assert not inserted, response
            return AUTHORIZATION_UNKNOWN_TOKEN

        if already_liked_response.results:
            assert not inserted, response
            return ALREADY_LIKED_RESPONSE

        assert inserted, response
        assert insert_like_response.rows_affected == 1, response
        return Response(
            content=LikeCourseResponse(liked_at=request_at).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=201,
        )
