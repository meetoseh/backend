from fastapi import APIRouter, Header
from typing import Optional
from error_middleware import handle_contextless_error
from models import STANDARD_ERRORS_BY_CODE, AUTHORIZATION_UNKNOWN_TOKEN
from courses.auth import auth_any
from itgs import Itgs
from content_files.lib.serve_s3_file import serve_s3_file, ServableS3File


router = APIRouter()


@router.get(
    "/download/{uid}.zip",
    status_code=200,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def finish_course_download(uid: str, authorization: Optional[str] = Header(None)):
    """Actually streams the course download for the course with
    the given uid.

    Requires a course JWT for the course with that uid provided via the
    authorization header, in the standard `bearer {token}` format.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        if auth_result.result.course_uid != uid:
            return AUTHORIZATION_UNKNOWN_TOKEN

        conn = await itgs.conn()
        cursor = conn.cursor("none")

        response = await cursor.execute(
            """
            SELECT
                s3_files.uid,
                s3_files.key,
                s3_files.file_size
            FROM course_exports, courses
            JOIN s3_files ON s3_files.id = course_exports.s3_file_id
            WHERE
                course_exports.course_id = courses.id
                AND courses.uid = ?
            ORDER BY course_exports.created_at DESC, course_exports.uid ASC 
            LIMIT 1
            """,
            (uid,),
        )
        if not response.results:
            await handle_contextless_error(
                extra_info=f"received valid download request for course {uid=}, but no course exports were found"
            )
            return AUTHORIZATION_UNKNOWN_TOKEN

        s3_file_uid: str = response.results[0][0]
        s3_file_key: str = response.results[0][1]
        s3_file_size: int = response.results[0][2]

        return await serve_s3_file(
            itgs,
            ServableS3File(
                uid=s3_file_uid,
                key=s3_file_key,
                content_type="application/zip",
                file_size=s3_file_size,
            ),
        )
