import asyncio
import os
import secrets
import time
from fastapi import APIRouter, UploadFile, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Literal, Optional
from file_uploads.auth import auth_any
from itgs import Itgs
from models import (
    STANDARD_ERRORS_BY_CODE,
    AUTHORIZATION_UNKNOWN_TOKEN,
    StandardErrorResponse,
)
import json

router = APIRouter()


class FileUploadPartResponse(BaseModel):
    done: bool = Field(
        description="If the file upload completed and moved to processing as a result of this request",
    )


ERROR_404_TYPE = Literal["upload_aborted_or_completed", "part_does_not_exist"]
"""The error codes for the 404 response"""

ERROR_409_TYPE = Literal["part_already_uploaded", "part_does_not_match"]
"""The error codes for the 409 response"""


@router.post(
    "/{uid}/{part}",
    status_code=202,
    response_model=FileUploadPartResponse,
    responses={
        "404": {
            "description": "One of: the upload was aborted or completed, or there is no part with that number for the upload",
            "model": StandardErrorResponse[ERROR_404_TYPE],
        },
        "409": {
            "description": "One of: the part has already been uploaded, the provided file is not the correct length for that part",
            "model": StandardErrorResponse[ERROR_409_TYPE],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def upload_part(
    uid: str,
    part: int,
    file: UploadFile,
    jwt: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """The primary endpoint to upload a single part of a multipart upload.

    Either the `jwt` query parameter or the `authorization` header must be set.
    If both are set, the `jwt` query parameter is ignored. The JWT is not the
    standard authorization - rather, it's a JWT specifically for this file
    upload, returned from a more contextful endpoint (such as
    [create journey background image](#/journeys/create_journey_background_image_api_1_journeys_background_images__post))
    """
    token: Optional[str] = authorization
    if token is None and jwt is not None:
        token = f"bearer {jwt}"

    del jwt
    del authorization

    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, token)
        if not auth_result.success:
            return auth_result.error_response

        if auth_result.result.file_upload_uid != uid:
            return AUTHORIZATION_UNKNOWN_TOKEN

        conn = await itgs.conn()
        cursor = conn.cursor("strong")

        now = time.time()
        response = await cursor.execute(
            """
            SELECT
                s3_file_upload_parts.start_byte,
                s3_file_upload_parts.end_byte,
                s3_file_upload_parts.s3_file_id
            FROM s3_file_uploads
            LEFT OUTER JOIN s3_file_upload_parts ON (
                s3_file_uploads.id = s3_file_upload_parts.s3_file_upload_id
                AND s3_file_upload_parts.part_number = ?
            )
            WHERE
                s3_file_uploads.uid = ?
                AND s3_file_uploads.completed_at IS NULL
                AND s3_file_uploads.expires_at > ?
            """,
            (part, uid, now),
        )
        if not response.results:
            return JSONResponse(
                content=StandardErrorResponse[ERROR_404_TYPE](
                    type="upload_aborted_or_completed",
                    message=(
                        "The referenced upload does not exist, though the JWT is valid. This means "
                        "that the upload has already finished, i.e., it's either been aborted it it "
                        "finished successfully."
                    ),
                ).dict(),
                status_code=404,
            )

        start_byte: Optional[int] = response.results[0][0]
        end_byte: Optional[int] = response.results[0][1]
        s3_file_id: Optional[int] = response.results[0][2]

        if start_byte is None or end_byte is None:
            return JSONResponse(
                content=StandardErrorResponse[ERROR_404_TYPE](
                    type="part_does_not_exist",
                    message=(
                        "The referenced part does not exist for the referenced upload. The server "
                        "decides how the parts are split up, and the parts and corresponding byte ranges "
                        "should have been returned from the same endpoint you used to get the JWT."
                    ),
                ).dict(),
                status_code=404,
            )

        if s3_file_id is not None:
            return JSONResponse(
                content=StandardErrorResponse[ERROR_409_TYPE](
                    type="part_already_uploaded",
                    message=(
                        "The referenced part has already been uploaded. This is likely a duplicate "
                        "request."
                    ),
                ).dict(),
                status_code=409,
            )

        file.file.seek(0, os.SEEK_END)
        file_size = file.file.tell()
        file.file.seek(0)
        if end_byte - start_byte != file_size:
            return JSONResponse(
                content=StandardErrorResponse[ERROR_409_TYPE](
                    type="part_does_not_match",
                    message=(
                        "The referenced part does not match the expected length. The server "
                        "decides how the parts are split up, and the parts and corresponding byte ranges "
                        "should have been returned from the same endpoint you used to get the JWT. You provided "
                        f"a file with {file_size} bytes, but the server expected {end_byte - start_byte} "
                        f"bytes for this part; bytes [{start_byte}, {end_byte})."
                    ),
                ).dict(),
                status_code=409,
            )
        files = await itgs.files()
        redis = await itgs.redis()
        key = f"s3_files/uploads/{uid}/{part}/{secrets.token_urlsafe(8)}"
        purgatory_key = json.dumps(
            {"bucket": files.default_bucket, "key": key}, sort_keys=True
        )

        await redis.zadd("files:purgatory", {purgatory_key: now + 600})
        await files.upload(file.file, bucket=files.default_bucket, key=key, sync=True)
        s3_file_uid = f"oseh_s3f_{secrets.token_urlsafe(16)}"
        response = await cursor.executemany3(
            (
                # INSERT INTO s3_files
                (
                    """
                    INSERT INTO s3_files (
                        uid, key, file_size, content_type, created_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (s3_file_uid, key, file_size, "application/octet-stream", now),
                ),
                # UPDATE s3_file_upload_parts
                (
                    """
                    UPDATE s3_file_upload_parts
                    SET s3_file_id = s3_files.id
                    FROM s3_files
                    WHERE
                        s3_files.uid = ?
                        AND EXISTS (
                            SELECT 1 FROM s3_file_uploads
                            WHERE s3_file_upload_parts.s3_file_upload_id = s3_file_uploads.id
                            AND s3_file_uploads.uid = ?
                        )
                        AND s3_file_upload_parts.part_number = ?
                        AND s3_file_upload_parts.s3_file_id IS NULL
                    """,
                    (
                        s3_file_uid,
                        uid,
                        part,
                    ),
                ),
                # mark complete if all parts uploaded (we'll check rows_affected)
                (
                    """
                    UPDATE s3_file_uploads
                    SET completed_at = ?
                    WHERE
                        s3_file_uploads.uid = ?
                        AND EXISTS (
                            SELECT 1 FROM s3_file_upload_parts
                            WHERE s3_file_upload_parts.s3_file_upload_id = s3_file_uploads.id
                            AND s3_file_upload_parts.part_number = ?
                            AND EXISTS (
                                SELECT 1 FROM s3_files
                                WHERE s3_files.id = s3_file_upload_parts.s3_file_id
                                AND s3_files.uid = ?
                            )
                        )
                        AND NOT EXISTS (
                            SELECT 1 FROM s3_file_upload_parts
                            WHERE s3_file_upload_parts.s3_file_upload_id = s3_file_uploads.id
                            AND s3_file_upload_parts.s3_file_id IS NULL
                        )
                        AND s3_file_uploads.completed_at IS NULL
                    """,
                    (
                        now,
                        uid,
                        part,
                        s3_file_uid,
                    ),
                ),
            )
        )

        part_was_accepted = (
            response.items[1].rows_affected is not None
            and response.items[1].rows_affected > 0
        )
        if not part_was_accepted:
            await asyncio.gather(
                cursor.execute("DELETE FROM s3_files WHERE uid=?", (s3_file_uid,)),
                files.delete(bucket=files.default_bucket, key=key),
            )
            await redis.zrem("files:purgatory", purgatory_key)
            return JSONResponse(
                content=StandardErrorResponse[ERROR_409_TYPE](
                    type="part_already_uploaded",
                    message=(
                        "While the referenced part was being uploaded, a different request to upload "
                        "that part completed. The part from this request was discarded. This is likely "
                        "a duplicate request."
                    ),
                ).dict(),
                status_code=409,
            )

        await redis.zrem("files:purgatory", purgatory_key)

        upload_is_complete = (
            response.items[2].rows_affected is not None
            and response.items[2].rows_affected > 0
        )
        if not upload_is_complete:
            return JSONResponse(
                content=FileUploadPartResponse(done=False).dict(), status_code=202
            )

        response = await cursor.execute(
            "SELECT success_job_name, success_job_kwargs FROM s3_file_uploads WHERE uid=?",
            (uid,),
        )
        assert response.results, f"{response=}, {uid=} should have been found"
        success_job_name: str = response.results[0][0]
        success_job_kwargs_str: str = response.results[0][1]

        success_job_kwargs = json.loads(success_job_kwargs_str)
        assert isinstance(
            success_job_kwargs, dict
        ), f"{success_job_name=}, {success_job_kwargs_str=}"

        jobs = await itgs.jobs()
        await jobs.enqueue(success_job_name, **success_job_kwargs)
        return JSONResponse(
            content=FileUploadPartResponse(done=True).dict(), status_code=202
        )
