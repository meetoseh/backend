import json
import secrets
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response, StreamingResponse
from typing import Optional, List, Union, cast as typing_cast
from pydantic import BaseModel, Field
from itgs import Itgs
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE
from content_files.lib.serve_s3_file import read_in_parts, read_file_in_parts
import unix_dates
import pytz
import datetime
import io
import os
from utms.lib.parse import get_utm_parts

router = APIRouter()


class UTMResponse(BaseModel):
    source: str = Field(description="The source of the utm")
    medium: Optional[str] = Field(description="The medium of the utm; omitted if none")
    campaign: Optional[str] = Field(
        description="The campaign of the utm; omitted if none"
    )
    content: Optional[str] = Field(
        description="The content of the utm; omitted if none"
    )
    term: Optional[str] = Field(description="The term of the utm; omitted if none")


class UTMConversionStatsResponseItem(BaseModel):
    utm: UTMResponse = Field(description="The utm these stats are for")
    retrieved_for: str = Field(description="The date these stats are for")
    visits: int = Field(
        description="The number of visits that came from this utm on the given day"
    )
    holdover_preexisting: int = Field(
        description="Visitors from previous days related to this utm on an existing account today"
    )
    holdover_last_click_signups: int = Field(
        description=(
            "Number of visitors from previous days whose last utm click was this one and who "
            "converted to an account this day"
        )
    )
    holdover_any_click_signups: int = Field(
        description=(
            "Number of visitors from previous days who clicked this utm and who converted to an "
            "account this day"
        )
    )
    preexisting: int = Field(
        description=(
            "Visitors created this day associated with an already existing account this day."
        )
    )
    last_click_signups: int = Field(
        description=(
            "Visitors created this day whose last click before converting to a new user was this utm."
        )
    )
    any_click_signups: int = Field(
        description=("Visitors created this day who converted to a new user this day.")
    )


class UTMConversionStatsResponse(BaseModel):
    rows: List[UTMConversionStatsResponseItem] = Field(
        description="The list of utm conversion stats rows"
    )
    retrieved_at: float = Field(
        description="The time these stats were retrieved at, in seconds since the unix epoch"
    )


tz = pytz.timezone("America/Los_Angeles")


@router.get(
    "/utm_conversion_stats",
    response_model=UTMConversionStatsResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_utm_conversion_stats(
    year: int, month: int, day: int, authorization: Optional[str] = Header(None)
):
    """Fetches utm conversion stats for the given date. If the stats are not available
    yet, a response with no rows will be returned. The retrieved_at time can be used
    to determine if the stats were fetched from a cache or not.

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        cur_unix_date = unix_dates.unix_date_today(tz=tz)
        req_unix_date = unix_dates.date_to_unix_date(datetime.date(year, month, day))

        if req_unix_date > cur_unix_date:
            return Response(
                content=UTMConversionStatsResponse(
                    rows=[], retrieved_at=time.time()
                ).model_dump_json(),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                },
                status_code=200,
            )

        return await get_response_for_date(itgs, req_unix_date, cur_unix_date)


async def get_response_for_date(
    itgs: Itgs, req_unix_date: int, cur_unix_date: int
) -> Response:
    """Determines the response for the given date, fetching it from the nearest
    cache if it's cacheable, filling along the way. This will stream the response
    if it's appropriate to do so, otherwise it will return a non-streaming response.

    Args:
        itgs (Itgs): The integrations to (re)use
        req_unix_date (int): The unix date requested
        cur_unix_date (int): The current unix date. Used to save time when determining
            where the data is by choosing more likely locations first.

    Returns:
        Response: The response to return
    """
    if req_unix_date >= cur_unix_date:
        tmp_file = await get_response_from_redis_as_temp_file(itgs, req_unix_date)
        if tmp_file is not None:
            return StreamingResponse(
                content=read_file_in_parts(tmp_file, delete_after=True),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                },
            )

        return Response(
            content=UTMConversionStatsResponse(
                rows=[], retrieved_at=time.time()
            ).model_dump_json(),
            headers={
                "Content-Type": "application/json; charset=utf-8",
            },
        )

    resp = await get_response_from_local_cache(itgs, req_unix_date)
    if resp is not None:
        return resp

    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": "private, max-age=86400, stale-while-revalidate=86400, stale-if-error=86400",
    }

    tmp_file = await get_response_from_db_as_temp_file(itgs, req_unix_date)
    if tmp_file is not None:
        try:
            with open(tmp_file, "rb") as f:
                await set_response_in_local_cache(itgs, req_unix_date, f)
        except:
            os.unlink(tmp_file)
            raise

        return StreamingResponse(
            content=read_file_in_parts(tmp_file, delete_after=True),
            headers=headers,
        )

    tmp_file = await get_response_from_redis_as_temp_file(itgs, req_unix_date)
    if tmp_file is None:
        return Response(
            content=UTMConversionStatsResponse(
                rows=[], retrieved_at=time.time()
            ).model_dump_json(),
            headers=headers,
        )

    return StreamingResponse(
        content=read_file_in_parts(tmp_file, delete_after=True),
        headers=headers,
    )


async def get_response_from_redis_as_temp_file(
    itgs: Itgs, unix_date: int
) -> Optional[str]:
    """Writes the utm conversion stats for the given date from redis to a temp file,
    if they are available in redis, and returns the path to the temp file.

    Args:
        itgs (Itgs): The integrations to (re)use
        unix_date (str): The unix date to fetch the stats for

    Returns:
        (str or None): The path to the temp file if available, or None if not
    """
    os.makedirs("tmp", exist_ok=True)
    tmp_file = os.path.join("tmp", secrets.token_hex(16))

    try:
        with open(tmp_file, "wb") as out:
            success = await write_response_from_redis(itgs, unix_date, out)
    except:
        os.unlink(tmp_file)
        raise

    if not success:
        os.unlink(tmp_file)
        return None

    return tmp_file


async def get_response_from_db_as_temp_file(
    itgs: Itgs, unix_date: int
) -> Optional[str]:
    """Writes the utm conversion stats for the given date from the database to a temp file,
    if they are available in redis, and returns the path to the temp file.

    Args:
        itgs (Itgs): The integrations to (re)use
        unix_date (str): The unix date to fetch the stats for

    Returns:
        (str or None): The path to the temp file if available, or None if not
    """
    os.makedirs("tmp", exist_ok=True)
    tmp_file = os.path.join("tmp", secrets.token_hex(16))

    try:
        with open(tmp_file, "wb") as out:
            success = await write_response_from_db(itgs, unix_date, out)
    except:
        os.unlink(tmp_file)
        raise

    if not success:
        os.unlink(tmp_file)
        return None

    return tmp_file


async def get_response_from_local_cache(
    itgs: Itgs, unix_date: int
) -> Optional[Response]:
    """Fetches the utm conversion stats for the given date from the local cache, if
    available. This will stream the response if it's appropriate to do so.

    Args:
        itgs (Itgs): The integrations to (re)use
        unix_date (int): The unix date to fetch the stats for

    Returns:
        (Response or None): The response if available, or None if not
    """
    local_cache = await itgs.local_cache()
    res = typing_cast(
        Union[bytes, io.BytesIO, None],
        local_cache.get(f"utm_conversion_stats:{unix_date}".encode("ascii"), read=True),
    )
    if res is None:
        return None

    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": "private, max-age=86400, stale-while-revalidate=86400, stale-if-error=86400",
    }

    if isinstance(res, (bytes, bytearray, memoryview)):
        return Response(
            content=res,
            status_code=200,
            headers=headers,
        )

    return StreamingResponse(
        content=read_in_parts(res),
        status_code=200,
        headers=headers,
    )


async def set_response_in_local_cache(
    itgs: Itgs, unix_date: int, raw: io.BufferedReader
) -> None:
    """Writes the given raw response to the local cache for the given date

    Args:
        itgs (Itgs): The integrations to (re)use
        unix_date (int): The unix date to write the stats for
        raw (io.BytesIO): The raw response to write to the cache
    """
    local_cache = await itgs.local_cache()
    local_cache.set(
        f"utm_conversion_stats:{unix_date}".encode("ascii"),
        raw,
        read=True,
        expire=60 * 60 * 24,
    )


async def write_response_from_redis(
    itgs: Itgs, req_unix_date: int, out: io.BufferedWriter
) -> bool:
    """If the utm conversion stats are available in redis for the given day,
    writes those stats to the given writer. Otherwise, returns False

    Args:
        itgs (Itgs): The integrations to (re)use
        req_unix_date (int): The unix date to fetch stats for
        out (io.BytesIO): The writer to write the stats to

    Returns:
        bool: True if stats were found and written, False if there was
            no information in the redis and nothing was written
    """
    redis = await itgs.redis()
    earliest_raw = await redis.get(b"stats:visitors:daily:earliest")
    if earliest_raw is None or int(earliest_raw) > req_unix_date:
        return False

    retrieved_for = json.dumps(
        unix_dates.unix_date_to_date(req_unix_date).isoformat()
    ).encode("utf-8")

    out.write(b'{"rows":[')
    first = True

    cursor: Optional[int] = None
    utms_set_key = f"stats:visitors:daily:{req_unix_date}:utms".encode("utf-8")
    while cursor is None or int(cursor) != 0:
        cursor, utms_bytes = await redis.sscan(
            utms_set_key, cursor=cursor if cursor is not None else 0
        )
        for raw_utm in utms_bytes:
            if isinstance(raw_utm, str):
                utm = raw_utm
            elif isinstance(raw_utm, bytes):
                utm = raw_utm.decode("utf-8")
            else:
                raise Exception(f"Unexpected type for {raw_utm=}: {type(raw_utm)}")

            utm_parts = get_utm_parts(utm)
            assert utm_parts is not None, utm
            (
                visits_raw,
                holdover_preexisting_raw,
                holdover_last_click_signups_raw,
                holdover_any_click_signups_raw,
                preexisting_raw,
                last_click_signups_raw,
                any_click_signups_raw,
            ) = await redis.hmget(  # type: ignore
                f"stats:visitors:daily:{utm}:{req_unix_date}:counts".encode("utf-8"),  # type: ignore
                [
                    b"visits",
                    b"holdover_preexisting",
                    b"holdover_last_click_signups",
                    b"holdover_any_click_signups",
                    b"preexisting",
                    b"last_click_signups",
                    b"any_click_signups",
                ],
            )

            visits = int(visits_raw) if visits_raw is not None else 0
            holdover_preexisting = (
                int(holdover_preexisting_raw)
                if holdover_preexisting_raw is not None
                else 0
            )
            holdover_last_click_signups = (
                int(holdover_last_click_signups_raw)
                if holdover_last_click_signups_raw is not None
                else 0
            )
            holdover_any_click_signups = (
                int(holdover_any_click_signups_raw)
                if holdover_any_click_signups_raw is not None
                else 0
            )
            preexisting = int(preexisting_raw) if preexisting_raw is not None else 0
            last_click_signups = (
                int(last_click_signups_raw) if last_click_signups_raw is not None else 0
            )
            any_click_signups = (
                int(any_click_signups_raw) if any_click_signups_raw is not None else 0
            )

            if first:
                first = False
            else:
                out.write(b",")

            out.write(b'{"utm":{"source":')
            out.write(json.dumps(utm_parts.source).encode("utf-8"))
            if utm_parts.medium is not None:
                out.write(b',"medium":')
                out.write(json.dumps(utm_parts.medium).encode("utf-8"))
            if utm_parts.campaign is not None:
                out.write(b',"campaign":')
                out.write(json.dumps(utm_parts.campaign).encode("utf-8"))
            if utm_parts.content is not None:
                out.write(b',"content":')
                out.write(json.dumps(utm_parts.content).encode("utf-8"))
            if utm_parts.term is not None:
                out.write(b',"term":')
                out.write(json.dumps(utm_parts.term).encode("utf-8"))
            out.write(b'},"retrieved_for":')
            out.write(retrieved_for)
            out.write(b',"visits":')
            out.write(str(visits).encode("ascii"))
            out.write(b',"holdover_preexisting":')
            out.write(str(holdover_preexisting).encode("ascii"))
            out.write(b',"holdover_last_click_signups":')
            out.write(str(holdover_last_click_signups).encode("ascii"))
            out.write(b',"holdover_any_click_signups":')
            out.write(str(holdover_any_click_signups).encode("ascii"))
            out.write(b',"preexisting":')
            out.write(str(preexisting).encode("ascii"))
            out.write(b',"last_click_signups":')
            out.write(str(last_click_signups).encode("ascii"))
            out.write(b',"any_click_signups":')
            out.write(str(any_click_signups).encode("ascii"))
            out.write(b"}")

    out.write(b'],"retrieved_at":')
    out.write(str(time.time()).encode("ascii"))
    out.write(b"}")
    return True


async def write_response_from_db(
    itgs: Itgs, req_unix_date: int, out: io.BufferedWriter
) -> bool:
    """If the utm conversion stats are available in the database for the given day,
    writes those stats to the given writer. Otherwise, returns False

    Args:
        itgs (Itgs): The integrations to (re)use
        req_unix_date (int): The unix date to fetch stats for
        out (io.BytesIO): The writer to write the stats to

    Returns:
        bool: True if stats were found and written, False if there was
            no information in the database and nothing was written
    """

    retrieved_for = json.dumps(
        unix_dates.unix_date_to_date(req_unix_date).isoformat()
    ).encode("utf-8")

    conn = await itgs.conn()
    cursor = conn.cursor("none")

    max_per_query = 50
    last_id: Optional[int] = None

    while True:
        response = await cursor.execute(
            """
            SELECT
                daily_utm_conversion_stats.id,
                utms.utm_source,
                utms.utm_medium,
                utms.utm_campaign,
                utms.utm_content,
                utms.utm_term,
                daily_utm_conversion_stats.visits,
                daily_utm_conversion_stats.holdover_preexisting,
                daily_utm_conversion_stats.holdover_last_click_signups,
                daily_utm_conversion_stats.holdover_any_click_signups,
                daily_utm_conversion_stats.preexisting,
                daily_utm_conversion_stats.last_click_signups,
                daily_utm_conversion_stats.any_click_signups
            FROM daily_utm_conversion_stats, utms
            WHERE
                daily_utm_conversion_stats.retrieved_for = ?
                AND daily_utm_conversion_stats.utm_id = utms.id
                AND (
                    ? IS NULL OR daily_utm_conversion_stats.id > ?
                )
            ORDER BY daily_utm_conversion_stats.id ASC
            LIMIT ?
            """,
            (
                unix_dates.unix_date_to_date(req_unix_date).isoformat(),
                last_id,
                last_id,
                max_per_query,
            ),
        )

        if not response.results:
            break

        is_first_row = last_id is None
        if is_first_row:
            out.write(b'{"rows":[')

        last_id = response.results[-1][0]

        for row in response.results:
            if not is_first_row:
                out.write(b",")
            else:
                is_first_row = False
            source: str = row[1]
            medium: Optional[str] = row[2]
            campaign: Optional[str] = row[3]
            content: Optional[str] = row[4]
            term: Optional[str] = row[5]
            visits: int = row[6]
            holdover_preexisting: int = row[7]
            holdover_last_click_signups: int = row[8]
            holdover_any_click_signups: int = row[9]
            preexisting: int = row[10]
            last_click_signups: int = row[11]
            any_click_signups: int = row[12]

            out.write(b'{"utm":{"source":')
            out.write(json.dumps(source).encode("utf-8"))
            if medium is not None:
                out.write(b',"medium":')
                out.write(json.dumps(medium).encode("utf-8"))
            if campaign is not None:
                out.write(b',"campaign":')
                out.write(json.dumps(campaign).encode("utf-8"))
            if content is not None:
                out.write(b',"content":')
                out.write(json.dumps(content).encode("utf-8"))
            if term is not None:
                out.write(b',"term":')
                out.write(json.dumps(term).encode("utf-8"))
            out.write(b'},"retrieved_for":')
            out.write(retrieved_for)
            out.write(b',"visits":')
            out.write(str(visits).encode("ascii"))
            out.write(b',"holdover_preexisting":')
            out.write(str(holdover_preexisting).encode("ascii"))
            out.write(b',"holdover_last_click_signups":')
            out.write(str(holdover_last_click_signups).encode("ascii"))
            out.write(b',"holdover_any_click_signups":')
            out.write(str(holdover_any_click_signups).encode("ascii"))
            out.write(b',"preexisting":')
            out.write(str(preexisting).encode("ascii"))
            out.write(b',"last_click_signups":')
            out.write(str(last_click_signups).encode("ascii"))
            out.write(b',"any_click_signups":')
            out.write(str(any_click_signups).encode("ascii"))
            out.write(b"}")

        if len(response.results) < max_per_query:
            break

    if last_id is None:
        return False

    out.write(b'],"retrieved_at":')
    out.write(str(time.time()).encode("ascii"))
    out.write(b"}")
    return True
