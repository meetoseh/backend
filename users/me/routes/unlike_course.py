from fastapi import APIRouter, Header
from fastapi.responses import Response
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


ERROR_404_TYPES = Literal["course_not_found"]
COURSE_NOT_FOUND_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="course_not_found",
        message="There is no course with that uid",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=404,
)

ERROR_409_TYPES = Literal["not_liked"]
NOT_LIKED_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_409_TYPES](
        type="not_liked",
        message="The user has not liked this course",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=409,
)


@router.delete(
    "/courses/likes",
    status_code=204,
    responses={
        "404": {
            "description": "There is no course with that uid",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        "409": {
            "description": "The user has not liked this course",
            "model": StandardErrorResponse[ERROR_409_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def unlike_course(
    uid: str, jwt: str, authorization: Annotated[Optional[str], Header()] = None
):
    """Unlikes the course with the given uid, which the user has access to
    via the jwt for that course with the LIKE flag set, and which the user
    has previously liked.

    Requires standard authorization for a user whose liked the course
    with the given uid.
    """
    async with Itgs() as itgs:
        std_auth_result = await std_auth.auth_any(itgs, authorization)
        if std_auth_result.result is None:
            return std_auth_result.error_response

        course_auth_result = await courses_auth.auth_any(itgs, f"bearer {jwt}")
        if course_auth_result.result is None:
            return course_auth_result.error_response

        if (
            course_auth_result.result.course_uid != uid
            or (
                course_auth_result.result.oseh_flags
                & courses_auth.CourseAccessFlags.LIKE
            )
            == 0
        ):
            return AUTHORIZATION_UNKNOWN_TOKEN

        conn = await itgs.conn()
        cursor = conn.cursor("strong")

        response = await cursor.executeunified3(
            (
                ("SELECT 1 FROM courses WHERE uid=?", (uid,)),
                ("SELECT 1 FROM users WHERE sub=?", (std_auth_result.result.sub,)),
                (
                    "DELETE FROM user_course_likes "
                    "WHERE"
                    " EXISTS ("
                    "  SELECT 1 FROM users"
                    "  WHERE"
                    "   users.id = user_course_likes.user_id"
                    "   AND users.sub = ?"
                    " )"
                    " AND EXISTS ("
                    "  SELECT 1 FROM courses"
                    "  WHERE"
                    "   courses.id = user_course_likes.course_id"
                    "   AND courses.uid = ?"
                    " )",
                    (std_auth_result.result.sub, uid),
                ),
            )
        )

        course_exists_response = response.items[0]
        user_exists_response = response.items[1]
        like_exists_response = response.items[2]

        deleted_like = (
            like_exists_response.rows_affected is not None
            and like_exists_response.rows_affected > 0
        )

        if not course_exists_response.results:
            assert not deleted_like, response
            return COURSE_NOT_FOUND_RESPONSE

        if not user_exists_response.results:
            assert not deleted_like, response
            return AUTHORIZATION_UNKNOWN_TOKEN

        if not deleted_like:
            return NOT_LIKED_RESPONSE

        assert like_exists_response.rows_affected == 1, response
        return Response(status_code=204)
