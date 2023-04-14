import io
from fastapi import APIRouter, Header
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from typing import Dict, Iterable, List, Literal, Optional, Tuple
from auth import auth_admin
from content_files.lib.serve_s3_file import read_in_parts
from models import STANDARD_ERRORS_BY_CODE
from dataclasses import dataclass
from itgs import Itgs
import pytz
import unix_dates
import datetime
from loguru import logger

HEADERS = {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "private, max-age=300, stale-while-revalidate=600, stale-if-error=86400",
}
"""The headers we return on success"""


router = APIRouter()


class ReadDailyPhoneVerificationsResponse(BaseModel):
    labels: List[str] = Field(
        description="The labels for the new users, where each label is represented as YYYY-MM-DD"
    )
    total: List[int] = Field(
        description="The number of approved phone verifications for each label"
    )
    users: List[int] = Field(
        description="The number of unique users who approved phone verifications for each label"
    )
    first: List[int] = Field(
        description="The number of phone verifications which were the first for their user for each label"
    )

    class Config:
        schema_extra = {
            "example": {
                "labels": ["2020-01-01", "2020-01-02", "2020-01-03"],
                "total": [10, 20, 30],
                "users": [8, 19, 30],
                "first": [7, 18, 30],
            }
        }


@dataclass
class ReadDailyPhoneVerificationDay:
    """The stats on a particular day, usually as a value within a map..
    The meaning for each value is as in ReadDailyPhoneVerificationsResponse
    """

    total: int
    users: int
    first: int


tz = pytz.timezone("America/Los_Angeles")


@router.get(
    "/daily_phone_verifications",
    status_code=200,
    response_model=ReadDailyPhoneVerificationsResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_daily_phone_verifications(
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    authorization: Optional[str] = Header(None),
) -> None:
    """Determines the number of approved phone verifications for each day
    in the given range. If one end of the range is not specified it's
    30 days from the other end. If neither end is specified, the end is
    yesterday. If the end date is today or later, it's replaced with today.
    The date ranges are inclusive. If the from date is after the to date,
    it's treated as if it wasn't set.

    Days are delineated by the America/Los_Angeles timezone.

    Dates are specified in isoformat (YYYY-MM-DD).

    This requires standard authorization for an admin user.
    """
    today = unix_dates.unix_date_today(tz=tz)

    parsed_from: Optional[datetime.date] = None
    if from_date is not None:
        try:
            parsed_from = datetime.date.fromisoformat(from_date)
        except:
            pass

    parsed_to: Optional[datetime.date] = None
    if to_date is not None:
        try:
            parsed_to = datetime.date.fromisoformat(to_date)
        except:
            pass

    if parsed_to is not None and unix_dates.date_to_unix_date(parsed_to) >= today:
        parsed_to = None

    if parsed_from is not None and parsed_to is not None and parsed_to < parsed_from:
        parsed_from = None

    from_unix_date: Optional[int] = None
    to_unix_date: Optional[int] = None

    if parsed_from is None and parsed_to is None:
        to_unix_date = today - 1
    elif parsed_from is None:
        to_unix_date = unix_dates.date_to_unix_date(parsed_to)
        if to_unix_date > today - 1:
            to_unix_date = today - 1
        from_unix_date = to_unix_date - 29
    elif parsed_to is None:
        from_unix_date = unix_dates.date_to_unix_date(parsed_from)
        to_unix_date = min(today - 1, from_unix_date + 29)
        if from_unix_date > to_unix_date:
            from_unix_date = to_unix_date
    else:
        from_unix_date = unix_dates.date_to_unix_date(parsed_from)
        to_unix_date = unix_dates.date_to_unix_date(parsed_to)
        if to_unix_date > today - 1:
            to_unix_date = today - 1
        if from_unix_date > to_unix_date:
            from_unix_date = to_unix_date

    # avoid querying & caching old dates that definitely don't exist; 19358 is jan 1 2023
    if from_unix_date < 19358:
        from_unix_date = 19358
        if to_unix_date < from_unix_date:
            to_unix_date = from_unix_date

    logger.debug(
        f"Interpreting {from_date=}, {to_date=} as {from_unix_date=}, {to_unix_date=} "
        f"({unix_dates.unix_date_to_date(from_unix_date).isoformat()} to {unix_dates.unix_date_to_date(to_unix_date).isoformat()}; "
        f"{to_unix_date - from_unix_date + 1} days)"
    )

    del from_date
    del to_date
    del parsed_from
    del parsed_to

    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        return await get_daily_phone_verifications(
            itgs, from_unix_date=from_unix_date, to_unix_date=to_unix_date
        )


async def get_daily_phone_verifications(
    itgs: Itgs, *, from_unix_date: int, to_unix_date: int
) -> Response:
    """Gets the number of approved phone verifications for each day from
    the nearest cache, if available, otherwise from the database.

    Returns the value as either a response or streaming response, as
    appropriate based on its size and where it's coming from.

    This caches for a day in the local cache and for a week in redis,
    though the redis cache is broken down by day and thus this instance
    has to go through a serialization step to convert it to an actual
    response.

    Args:
        itgs (Itgs): the integrations to (re)use
        from_unix_date (int): the first day to include, inclusive
        to_unix_date (int): the last day to include, inclusive
    """
    cached = await get_daily_phone_verifications_from_local_cache(
        itgs, from_unix_date=from_unix_date, to_unix_date=to_unix_date
    )
    if cached is not None:
        return cached

    cached_days = await get_daily_phone_verifications_from_redis(
        itgs, from_unix_date=from_unix_date, to_unix_date=to_unix_date
    )

    missing_days: List[int] = [
        unix_date
        for unix_date in range(from_unix_date, to_unix_date + 1)
        if unix_date not in cached_days
    ]
    for start, stop in iter_contiguous_ranges(missing_days):
        data = await get_daily_phone_verifications_from_db(
            itgs, from_unix_date=start, to_unix_date=stop
        )
        for i in range(start, stop + 1):
            cached_days[i] = data[i - start]

    await write_daily_phone_verifications_to_redis(
        itgs, data=dict((i, cached_days[i]) for i in missing_days)
    )

    serialized = (
        ReadDailyPhoneVerificationsResponse(
            labels=[
                unix_dates.unix_date_to_date(i).isoformat()
                for i in range(from_unix_date, to_unix_date + 1)
            ],
            total=[
                cached_days[i].total for i in range(from_unix_date, to_unix_date + 1)
            ],
            users=[
                cached_days[i].users for i in range(from_unix_date, to_unix_date + 1)
            ],
            first=[
                cached_days[i].first for i in range(from_unix_date, to_unix_date + 1)
            ],
        )
        .json()
        .encode("utf-8")
    )
    await write_daily_phone_verifications_to_local_cache(
        itgs,
        from_unix_date=from_unix_date,
        to_unix_date=to_unix_date,
        serialized=serialized,
    )
    return Response(content=serialized, headers=HEADERS)


def iter_contiguous_ranges(src: Iterable[int]) -> Iterable[Tuple[int, int]]:
    """Returns an iterator that yields (start, stop) pairs, inclusive
    on both ends, which are in the src iterable. The src iterable must
    already be in sorted ascending order.

    Example:
       [1, 2, 4, 5, 6, 7, 10] becomes [(1, 2), (4, 7), (10, 10)]

    Args:
        src (Iterable[int]): the iterable to iterate over

    Yields:
        Iterable[int]: the (start, stop) pairs
    """
    start = None
    stop = None
    for item in src:
        if start is None:
            start = item
            stop = item
        elif item == stop + 1:
            stop = item
        else:
            yield start, stop
            start = item
            stop = item

    if start is not None:
        yield start, stop


async def get_daily_phone_verifications_from_local_cache(
    itgs: Itgs, *, from_unix_date: int, to_unix_date: int
) -> Optional[Response]:
    """Fetches the daily phone verifications from the local cache for
    the given date range, if available, otherwise returns None.

    Args:
        itgs (Itgs): the integrations to (re)use
        from_unix_date (int): the first day to include, inclusive
        to_unix_date (int): the last day to include, inclusive

    Returns:
        Response, None: If the data is available, the data in the appropriate
            method for serving it, otherwise None
    """
    local_cache = await itgs.local_cache()
    raw = local_cache.get(
        f"daily_phone_verifications:{from_unix_date}:{to_unix_date}".encode("utf-8"),
        read=True,
    )
    if raw is None:
        return None

    if isinstance(raw, bytes):
        return Response(content=raw, status_code=200, headers=HEADERS)

    return StreamingResponse(
        content=read_in_parts(raw),
        status_code=200,
        headers=HEADERS,
    )


async def write_daily_phone_verifications_to_local_cache(
    itgs: Itgs, *, from_unix_date: int, to_unix_date: int, serialized: io.BytesIO
) -> None:
    """Stores the given serialized response for the given date range in
    the local cache.

    Args:
        itgs (Itgs): the integrations to (re)use
        from_unix_date (int): the first day to include, inclusive
        to_unix_date (int): the last day to include, inclusive
        serialized (io.BytesIO): the serialized response to store
    """
    local_cache = await itgs.local_cache()
    local_cache.set(
        f"daily_phone_verifications:{from_unix_date}:{to_unix_date}".encode("utf-8"),
        serialized,
        read=True,
        expire=60 * 60 * 24,
    )


async def get_daily_phone_verifications_from_redis(
    itgs: Itgs, *, from_unix_date: int, to_unix_date: int
) -> Dict[int, ReadDailyPhoneVerificationDay]:
    """Fetches the daily phone verifications from redis for the given
    date range, if available, otherwise returns None. These values are
    stored in separate keys, one for each day, so the result may be
    missing any days in the range.

    Args:
        itgs (Itgs): the integrations to (re)use
        from_unix_date (int): the first day to include, inclusive
        to_unix_date (int): the last day to include, inclusive

    Returns:
        dict[int, ReadyDailyPhoneVerificationDay]: the values for each
            day in the range, where each day is represented as a unix
            date. Days for which no data is available in redis are omitted.
    """
    redis = await itgs.redis()

    result: Dict[int, ReadDailyPhoneVerificationDay] = dict()
    for start in range(from_unix_date, to_unix_date + 1, 50):
        async with redis.pipeline() as pipe:
            for i in range(50):
                if start + i > to_unix_date:
                    break
                await pipe.hmget(
                    f"daily_phone_verifications:{start + i}".encode("utf-8"),
                    b"total",
                    b"users",
                    b"first",
                )
            results = await pipe.execute()

        for i, (total, users, first) in enumerate(results):
            if total is not None:
                result[start + i] = ReadDailyPhoneVerificationDay(
                    total=int(total),
                    users=int(users),
                    first=int(first),
                )

    return result


async def write_daily_phone_verifications_to_redis(
    itgs: Itgs, *, data: Dict[int, ReadDailyPhoneVerificationDay]
) -> None:
    """Stores the given data in redis, where the data is represented as a
    mapping from unix dates to the data for that day.

    Args:
        itgs (Itgs): the integrations to (re)use
        data (dict[int, ReadyDailyPhoneVerificationDay]): the data to store
    """
    redis = await itgs.redis()

    iterator = iter(data.items())
    while True:
        had_entries = False
        async with redis.pipeline() as pipe:
            for _ in range(50):
                try:
                    date, value = next(iterator)
                except StopIteration:
                    break
                had_entries = True
                key = f"daily_phone_verifications:{date}".encode("utf-8")
                await pipe.hmset(
                    key,
                    {
                        b"total": str(value.total).encode("utf-8"),
                        b"users": str(value.users).encode("utf-8"),
                        b"first": str(value.first).encode("utf-8"),
                    },
                )
                await pipe.expire(key, 60 * 60 * 24 * 7)
            await pipe.execute()

        if not had_entries:
            break


async def get_daily_phone_verifications_from_db(
    itgs: Itgs, *, from_unix_date: int, to_unix_date: int
) -> List[ReadDailyPhoneVerificationDay]:
    """Fetches the daily phone verifications from the database for the
    given date range.

    Args:
        itgs (Itgs): the integrations to (re)use
        from_unix_date (int): the first day to include, inclusive
        to_unix_date (int): the last day to include, inclusive

    Returns:
        list[ReadyDailyPhoneVerificationDay]: the values for each day
            in the range, where index 0 corresponds to the from date
            and -1 corresponds to the to date.
    """
    conn = await itgs.conn()
    cursor = conn.cursor("none")

    # you might think there's a pattern here to make this one query; but there are
    # not always the same number of unix seconds in a day when using a timezone as
    # the delineator, esp America/Los_Angeles which has daylight savings time. With
    # a timezone, the day transitions at arbitrary times based on local politics.
    # I believe it is possible to optimize this, but not trivial to optimize this,
    # so i've left it open by ensuring this function is called with the widest ranges
    # that we need, so it has the maximum context to optimize the query.

    result: List[ReadDailyPhoneVerificationDay] = list()
    for date in range(from_unix_date, to_unix_date + 1):
        start_unix_time = unix_dates.unix_date_to_timestamp(date, tz=tz)
        end_unix_time = unix_dates.unix_date_to_timestamp(date + 1, tz=tz)

        response = await cursor.execute(
            """
            SELECT
                COUNT(*) AS total,
                COUNT(DISTINCT phone_verifications.user_id) AS users,
                COUNT(first_users.id) AS first
            FROM phone_verifications
            LEFT OUTER JOIN users AS first_users ON (
                first_users.id = phone_verifications.user_id
                AND NOT EXISTS (
                    SELECT 1 FROM phone_verifications pv2
                    WHERE 
                        pv2.user_id = first_users.id
                        AND pv2.verified_at IS NOT NULL
                        AND (
                            pv2.verified_at < phone_verifications.verified_at
                            OR (
                                pv2.verified_at = phone_verifications.verified_at
                                AND pv2.uid < phone_verifications.uid
                            )
                        )
                )
            )
            WHERE
                phone_verifications.verified_at IS NOT NULL
                AND phone_verifications.verified_at >= ?
                AND phone_verifications.verified_at < ?
            """,
            (start_unix_time, end_unix_time),
        )

        total: int = response.results[0][0]
        users: int = response.results[0][1]
        first: int = response.results[0][2]

        result.append(
            ReadDailyPhoneVerificationDay(
                total=total,
                users=users,
                first=first,
            )
        )

    return result
