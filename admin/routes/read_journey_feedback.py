import io
from fastapi import APIRouter, Header
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from typing import List, Literal, Optional, Union
from auth import auth_admin
from journeys.routes.read import Journey, raw_read_journeys
from models import STANDARD_ERRORS_BY_CODE
from itgs import Itgs
import datetime
import json
from resources.filter_text_item import FilterTextItem
from resources.standard_text_operator import StandardTextOperator
import unix_dates
import pytz
import time
from temp_files import get_temp_file
from content_files.lib.serve_s3_file import read_file_in_parts, read_in_parts
import os


router = APIRouter()


class User(BaseModel):
    sub: str = Field(description="The sub of the user")
    given_name: str = Field(description="The given name of the user")
    family_name: str = Field(description="The family name of the user")
    created_at: float = Field(
        description="The time the user was created in seconds since the epoch"
    )


class Feedback(BaseModel):
    user: User = Field(description="The user who gave the feedback")
    liked: bool = Field(description="Whether the user liked the journey")
    strength: int = Field(
        description=(
            "The strength of the feedback. For yes/no questions this is always 1. "
            "For the 2-point scale, this is 1 or 2. For example, a two point scale "
            "question would be: 'Complete the sentence: I want to see...' with the "
            "options being 'Much more like this', 'More like this', 'Less like this', "
            "'Much less like this'. The strengths would be 2, 1, 1, 2 respectively."
        )
    )
    created_at: float = Field(
        description="The time the feedback was created in seconds since the epoch"
    )


class ReadJourneyFeedbackResponseItem(BaseModel):
    journey: Journey = Field(description="The journey the feedback is for")
    feedback: List[Feedback] = Field(description="The feedback for the journey")


class ReadJourneyFeedbackResponse(BaseModel):
    items: List[ReadJourneyFeedbackResponseItem] = Field(
        description="The feedback for the journeys"
    )
    retrieved_for: str = Field(
        description="The date that we retrieved feedback for, isoformatted"
    )
    retrieved_at: float = Field(
        description="The time the feedback was retrieved in seconds since the epoch"
    )


tz = pytz.timezone("America/Los_Angeles")


@router.get(
    "/journey_feedback",
    response_model=ReadJourneyFeedbackResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_journey_feedback(
    date: Optional[str] = None,
    authorization: Optional[str] = Header(None),
    pragma: Optional[Literal["no-cache"]] = Header(None),
):
    """Retrieves journey feedback that occurred on the given date. If no date is
    specified, retrieves journey feedback from yesterday. Dates are delineated via
    the America/Los_Angeles timezone, and dates at or after today always return no
    feedback.

    Requires standard authorization for an admin user.
    """
    date_iso = date
    del date

    date_parsed: Optional[datetime.date] = None
    if date_iso is not None:
        try:
            date_parsed = datetime.date.fromisoformat(date_iso)
        except ValueError:
            return Response(
                content=json.dumps(
                    {
                        "detail": [
                            {
                                "loc": ["query", "date"],
                                "msg": "Invalid date format",
                                "type": "value_error",
                            }
                        ]
                    }
                ),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=422,
            )

    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        now = time.time()
        today_unix_date = unix_dates.unix_timestamp_to_unix_date(now, tz=tz)
        req_unix_date = (
            unix_dates.date_to_unix_date(date_parsed)
            if date_parsed is not None
            else today_unix_date - 1
        )

        if req_unix_date >= today_unix_date:
            return Response(
                content=ReadJourneyFeedbackResponse(
                    items=[],
                    retrieved_for=unix_dates.unix_date_to_date(
                        req_unix_date
                    ).isoformat(),
                    retrieved_at=now,
                ).json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=200,
            )

        return await read_feedback_for_date(
            itgs, unix_date=req_unix_date, now=now, force=pragma == "no-cache"
        )


async def read_feedback_for_date(
    itgs: Itgs, *, unix_date: int, now: float, force: bool
) -> Response:
    """Fetches the journey feedback for the given date from the nearest
    cache, or from the database if no cached data is available, filling
    caches as it goes.

    Args:
        itgs (Itgs): the integrations to (re)use
        unix_date (int): the unix date to fetch feedback for
        now (float): the current time in seconds since the epoch
        force (bool): If true, skips the cache and goes straight to the database

    Returns:
        Response: The response object containing the ReadJourneyFeedbackResponse
            already serialized, since this process may not require a deserialization
            step.
    """
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": "private, max-age=10",
    }
    if not force:
        cached = await read_feedback_from_cache(itgs, unix_date=unix_date)
        if cached is not None:
            if isinstance(cached, bytes):
                return Response(content=cached, headers=headers, status_code=200)
            return StreamingResponse(
                content=read_in_parts(cached), headers=headers, status_code=200
            )

    tmp_file = get_temp_file()
    try:
        with open(tmp_file, "wb") as f:
            await read_feedback_from_db_and_write_to_file(
                itgs, unix_date=unix_date, now=now, out=f
            )
        with open(tmp_file, "rb") as f:
            await write_feedback_to_cache(itgs, unix_date=unix_date, feedback=f)
    except:
        os.unlink(tmp_file)
        raise

    return StreamingResponse(
        content=read_file_in_parts(tmp_file, delete_after=True),
        headers=headers,
        status_code=200,
    )


async def read_feedback_from_cache(
    itgs: Itgs, *, unix_date: int
) -> Optional[Union[bytes, io.BytesIO]]:
    """If journey feedback for the given date is available in the cache,
    returns the serialized representation either as fully-loaded bytes or
    as a file-like object. Otherwise, returns None.

    Args:
        itgs (Itgs): the integrations to (re)use
        unix_date (int): the unix date to fetch feedback for

    Returns:
        Optional[Union[bytes, io.BytesIO]]: The serialized representation
            of the feedback, or None if no feedback is available.
    """
    key = f"journey_feedback:{unix_date}".encode("ascii")
    cache = await itgs.local_cache()
    return cache.get(key, read=True)


async def write_feedback_to_cache(
    itgs: Itgs, *, unix_date: int, feedback: io.BytesIO
) -> None:
    """Writes the given serialized feedback to the cache for the given
    date. Caches expire after 15 minutes, to ensure jwts are still
    reasonably fresh.

    Args:
        itgs (Itgs): the integrations to (re)use
        unix_date (int): the unix date to fetch feedback for
        feedback (io.BytesIO): the serialized feedback to write
    """
    key = f"journey_feedback:{unix_date}".encode("ascii")
    cache = await itgs.local_cache()
    cache.set(key, feedback, read=True, expire=60 * 15)


async def read_feedback_from_db_and_write_to_file(
    itgs: Itgs, *, unix_date: int, now: float, out: io.BytesIO
) -> None:
    """Fetches the feedback for the given date from the database and
    writes it to the given file-like object.

    Args:
        itgs (Itgs): the integrations to (re)use
        unix_date (int): the unix date to fetch feedback for
        now (float): The current time for the purposes of the response

    Returns:
        ReadJourneyFeedbackResponse: the feedback for the given date
    """
    conn = await itgs.conn()
    cursor = conn.cursor("none")

    max_per_query = 50
    current_journey_id: Optional[int] = None
    last_journey_feedback_id: Optional[int] = None

    out.write(b'{"retrieved_for":"')
    out.write(unix_dates.unix_date_to_date(unix_date).isoformat().encode("ascii"))
    out.write(b'","retrieved_at":')
    out.write(str(now).encode("ascii"))
    out.write(b',"items":[')

    while True:
        response = await cursor.execute(
            """
            SELECT
                journey_feedback.id,
                journeys.id,
                journeys.uid,
                users.sub,
                users.given_name,
                users.family_name,
                users.created_at,
                journey_feedback.response,
                journey_feedback.created_at,
                journey_feedback.version
            FROM journey_feedback
            JOIN users ON users.id = journey_feedback.user_id
            JOIN journeys ON journeys.id = journey_feedback.journey_id
            WHERE
                journey_feedback.created_at >= ?
                AND journey_feedback.created_at < ?
                AND (
                    ? IS NULL OR (
                        journey_feedback.journey_id > ?
                        OR (
                            journey_feedback.journey_id = ?
                            AND journey_feedback.id > ?
                        )
                    )
                )
            ORDER BY journey_feedback.journey_id, journey_feedback.id
            LIMIT ?
            """,
            (
                unix_dates.unix_date_to_timestamp(unix_date, tz=tz),
                unix_dates.unix_date_to_timestamp(unix_date + 1, tz=tz),
                current_journey_id,
                current_journey_id,
                current_journey_id,
                last_journey_feedback_id,
                max_per_query,
            ),
        )

        if not response.results:
            break

        for row in response.results:
            row_journey_feedback_id: int = row[0]
            row_journey_id: int = row[1]
            row_journey_uid: str = row[2]
            row_user_sub: str = row[3]
            row_user_given_name: Optional[str] = row[4]
            row_user_family_name: Optional[str] = row[5]
            row_user_created_at: float = row[6]
            row_journey_feedback_response: int = int(row[7])
            row_journey_feedback_created_at: float = row[8]
            row_journey_feedback_version: int = row[9]

            if current_journey_id != row_journey_id:
                if current_journey_id is not None:
                    out.write(b"]},")

                current_journey_id = row_journey_id
                raw_journeys = await raw_read_journeys(
                    itgs,
                    filters_to_apply=[
                        (
                            "uid",
                            FilterTextItem(
                                operator=StandardTextOperator.EQUAL_CASE_SENSITIVE,
                                value=row_journey_uid,
                            ),
                        )
                    ],
                    sort=[],
                    limit=1,
                )
                assert len(raw_journeys) == 1
                out.write(b'{"journey":')
                out.write(raw_journeys[0].json().encode("utf-8"))
                out.write(b',"feedback":[')
            else:
                out.write(b",")

            out.write(b'{"user":{"sub":')
            out.write(json.dumps(row_user_sub).encode("utf-8"))
            out.write(b',"given_name":')
            out.write(json.dumps(row_user_given_name).encode("utf-8"))
            out.write(b',"family_name":')
            out.write(json.dumps(row_user_family_name).encode("utf-8"))
            out.write(b',"created_at":')
            out.write(str(row_user_created_at).encode("ascii"))
            out.write(b'},"liked":')
            if row_journey_feedback_version in (1, 2):
                out.write(b"true" if row_journey_feedback_response == 1 else b"false")
                out.write(b',"strength":1')
            else:
                out.write(
                    b"true" if row_journey_feedback_response in (1, 2) else b"false"
                )
                out.write(b',"strength":')
                out.write(
                    str(1 if row_journey_feedback_response in (2, 3) else 2).encode(
                        "ascii"
                    )
                )
            out.write(b',"created_at":')
            out.write(str(row_journey_feedback_created_at).encode("ascii"))
            out.write(b"}")

            last_journey_feedback_id = row_journey_feedback_id

        if len(response.results) < max_per_query:
            break

    if current_journey_id is not None:
        out.write(b"]}")

    out.write(b"]}")
