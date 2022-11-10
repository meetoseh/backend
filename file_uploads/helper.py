"""This module assists other modules which want to provide the user a way to
upload a file.
"""
import json
import time
from pydantic import BaseModel, Field
from typing import Dict, List, Union
from itgs import Itgs
from functools import cache
import itertools
import secrets


class FileUploadPartResponse(BaseModel):
    """Describes a single part of a file upload that the client is expected
    to make.
    """

    number: int = Field(
        description="The part number, where 1 is the first part, increasing by 1 for each consecutive part",
        ge=1,
    )
    start_byte: int = Field(
        description="The byte offset of the start of the part, inclusive", ge=0
    )
    end_byte: int = Field(
        description="The byte offset of the end of the part, exclusive", ge=0
    )


class FileUploadPartRangeResponse(BaseModel):
    """Describes a contiguous range of file upload parts which all have the same size."""

    start_number: int = Field(
        description="The number for the first part in this range", ge=0
    )
    start_byte: int = Field(
        description="The byte offset of the first part within this range, inclusive",
        ge=0,
    )
    number_of_parts: int = Field(description="How many parts are in this range", ge=1)
    part_size: int = Field(
        description="The number of bytes in each part in this range", ge=1
    )


class FileUploadResponse(BaseModel):
    """Allows the user to upload a file to the server via the upload part
    endpoint.
    """

    uid: str = Field(description="The UID of the file upload")
    jwt: str = Field(
        description="The JWT the client should use to authorize the upload"
    )
    parts: List[Union[FileUploadPartResponse, FileUploadPartRangeResponse]] = Field(
        description="The way the client is expected to split up the file for upload."
    )


async def start_upload(
    itgs: Itgs,
    *,
    file_size: int,
    success_job_name: str,
    success_job_kwargs: dict,
    failure_job_name: str,
    failure_job_kwargs: dict,
    s3_file_upload_uid_key_in_kwargs: str = "file_upload_uid",
    expires_in: int = 3600,
) -> FileUploadResponse:
    """Prepares the server to receive a file of the given size, in bytes,
    and returns the required information for the client to upload the file.

    Args:
        itgs (Itgs): The integrations to use to connect to networked services
        success_job_name (str): The name of the job to run when the file is successfully uploaded,
            e.g., "runners.example"
        success_job_kwargs (dict): The kwargs to pass to the success job. One additional
            key will be injected, see `s3_file_upload_uid_key_in_kwargs`.
        failure_job_name (str): The name of the job to run when the file fails to upload,
            e.g., "runners.example"
        failure_job_kwargs (dict): The kwargs to pass to the failure job. One additional
            key will be injected, see `s3_file_upload_uid_key_in_kwargs`.
        s3_file_upload_uid_key_in_kwargs (str): The key in the success and failure job kwargs
            which should be set to the uid of the s3_file_upload which succeeded/failed.
        expires_in (int): How long, in seconds, the file upload should be valid for. If the upload
            does not complete within this time, the failure job will be run.

    Returns:
        FileUploadResponse: The response to send to the client.
    """
    assert file_size > 0, f"{file_size=} must be positive"

    conn = await itgs.conn()
    cursor = conn.cursor("strong")

    s3_file_upload_uid = f"oseh_s3fu_{secrets.token_urlsafe(16)}"
    full_success_kwargs = {
        **success_job_kwargs,
        s3_file_upload_uid_key_in_kwargs: s3_file_upload_uid,
    }
    full_failure_kwargs = {
        **failure_job_kwargs,
        s3_file_upload_uid_key_in_kwargs: s3_file_upload_uid,
    }

    parts: List[Union[FileUploadPartResponse, FileUploadPartRangeResponse]] = []
    part_size = 1024 * 1024  # should be lte the spooling size for UploadFile
    num_full_parts = file_size // part_size
    if num_full_parts > 0:
        parts.append(
            FileUploadPartRangeResponse(
                start_number=1,
                start_byte=0,
                number_of_parts=num_full_parts,
                part_size=part_size,
            )
        )
    if num_full_parts * part_size < file_size:
        parts.append(
            FileUploadPartResponse(
                number=num_full_parts + 1,
                start_byte=num_full_parts * part_size,
                end_byte=file_size,
            )
        )

    now = time.time()
    await cursor.execute(
        """
        INSERT INTO s3_file_uploads (
            uid,
            success_job_name,
            success_job_kwargs,
            failure_job_name,
            failure_job_kwargs,
            created_at,
            completed_at,
            expires_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            s3_file_upload_uid,
            success_job_name,
            json.dumps(full_success_kwargs, sort_keys=True),
            failure_job_name,
            json.dumps(full_failure_kwargs, sort_keys=True),
            now,
            None,
            now + expires_in,
        ),
    )

    response = await cursor.execute(
        "SELECT id FROM s3_file_uploads WHERE uid=?",
        (s3_file_upload_uid,),
    )

    s3_file_upload_id: int = response.results[0][0]

    qmarks_1 = "(?,?,?,?,?)"

    def get_qmarks(num_inserts: int) -> str:
        return ",".join([qmarks_1] * num_inserts)

    @cache
    def get_query(num_inserts: int) -> str:
        return (
            "INSERT INTO s3_file_upload_parts "
            "(s3_file_upload_id, uid, part_number, start_byte, end_byte) "
            f"VALUES {get_qmarks(num_inserts)}"
        )

    num_per_insert = 100
    for full_part_num_start in range(1, num_full_parts + 1, num_per_insert):
        full_part_num_end = min(
            full_part_num_start + num_per_insert, num_full_parts + 1
        )
        response = await cursor.execute(
            get_query(full_part_num_end - full_part_num_start),
            tuple(
                itertools.chain.from_iterable(
                    (
                        s3_file_upload_id,
                        f"oseh_s3fup_{secrets.token_urlsafe(16)}",
                        i,
                        i * part_size,
                        (i + 1) * part_size,
                    )
                    for i in range(full_part_num_start, full_part_num_end)
                )
            ),
        )
        assert response.rows_affected == full_part_num_end - full_part_num_start

    if num_full_parts * part_size < file_size:
        response = await cursor.execute(
            get_query(1),
            (
                s3_file_upload_id,
                f"oseh_s3fup_{secrets.token_urlsafe(16)}",
                num_full_parts + 1,
                num_full_parts * part_size,
                file_size,
            ),
        )
        assert response.rows_affected == 1
