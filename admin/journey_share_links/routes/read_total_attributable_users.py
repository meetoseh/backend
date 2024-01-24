import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Annotated, Optional
from error_middleware import handle_warning
from models import STANDARD_ERRORS_BY_CODE
from auth import auth_admin
from itgs import Itgs
from redis_helpers.share_links_count_attributable_users import (
    ensure_share_links_count_attributable_users_script_exists,
    share_links_count_attributable_users,
)
import unix_dates
import pytz


class ReadTotalViewsResponse(BaseModel):
    value: int = Field(
        description="The total number of users attributable to share links since the beginning of time"
    )
    checked_at: float = Field(description="When this value was checked")


router = APIRouter()


@router.get(
    "/total_attributable_users",
    response_model=ReadTotalViewsResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_total_attributable_users(
    authorization: Annotated[Optional[str], Header()] = None
):
    """Reads the total number of users attributable to journey share
    links, used in the Sharing dashboard. This value is
    aggressively cached, and besides respecting cache-control headers,
    the client does not need to restrict the frequency of requests.

    Requires standard authorization for an admin user.
    """
    request_at = time.time()
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        result = await read_and_count_total_attributable_users(
            itgs, request_at=request_at
        )
        return Response(
            content=ReadTotalViewsResponse.__pydantic_serializer__.to_json(
                ReadTotalViewsResponse(value=result, checked_at=request_at)
            ),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "private, max-age=10, stale-while-revalidate=60, stale-if-error=3600",
            },
            status_code=200,
        )


EXPECTED_UTM_SOURCE = "oseh_app"
EXPECTED_UTM_MEDIUM = "referral"
EXPECTED_UTM_CAMPAIGN = "share_link"
# The above values cannot be changed without changes to source code;
# for one, the utm data won't have changed, for another, they are hardcoded
# into the redis script


class _PrecomputedSum(BaseModel):
    end_unix_date_excl: int = Field()
    total: int = Field()


async def read_and_count_total_attributable_users(
    itgs: Itgs, /, *, request_at: float
) -> int:
    """Using the precomputed sum, if available, this will determine the total
    number of users attributable to share links since the beginning of time.
    This will use the database if necessary, and will always use redis. Repeated
    calls within the same unix date will only hit redis, and generally the
    database will only be hit for rows inserted since this has been called,
    rather than always having to go from the beginning of time. This does mean
    that this value could get out of sync with the database, which can be
    resolved by deleting the precomputed sum from redis to have the value
    completely recomputed.
    """
    request_unix_date = unix_dates.unix_timestamp_to_unix_date(
        request_at, tz=pytz.timezone("America/Los_Angeles")
    )
    redis = await itgs.redis()
    earliest_in_redis = await redis.get(b"stats:visitors:daily:earliest")
    if earliest_in_redis is None:
        await handle_warning(
            f"{__name__}:visitor_daily_earliest_not_set",
            "Without stats:visitors:daily:earliest set we are likely to corrupt "
            "the precomputed sum; reporting total attributable users as 0. This might "
            "be correct if the environment was just started, but should be resolved "
            "within 5 minutes of the first view to any page supporting visitors",
        )
        return 0

    earliest_unix_date_in_redis = int(earliest_in_redis)
    del earliest_in_redis

    precomputed = await _read_precomputed_sum_from_redis(itgs)
    if precomputed is None:
        total_in_db = await _count_attributable_users_from_db(
            itgs,
            start_unix_date_incl=None,
            end_unix_date_excl=earliest_unix_date_in_redis,
        )
        precomputed = _PrecomputedSum(
            end_unix_date_excl=earliest_unix_date_in_redis, total=total_in_db
        )
        await _write_precomputed_sum_to_redis(itgs, sum=precomputed)
    elif precomputed.end_unix_date_excl < earliest_unix_date_in_redis:
        missing_parts = await _count_attributable_users_from_db(
            itgs,
            start_unix_date_incl=precomputed.end_unix_date_excl,
            end_unix_date_excl=earliest_unix_date_in_redis,
        )
        precomputed.total += missing_parts
        precomputed.end_unix_date_excl = earliest_unix_date_in_redis
        await _write_precomputed_sum_to_redis(itgs, sum=precomputed)

    redis_portion = await _count_attributable_users_from_redis(
        itgs,
        start_unix_date_incl=earliest_unix_date_in_redis,
        end_unix_date_excl=request_unix_date + 1,
    )

    return precomputed.total + redis_portion


async def _read_precomputed_sum_from_redis(itgs: Itgs, /) -> Optional[_PrecomputedSum]:
    """Reads the precomputed sum for all the database statistics up to and excluding
    a particular unix date which is available, if any is available
    """
    redis = await itgs.redis()
    result_raw = await redis.get(b"journey_share_links:total_attributable_users")
    if result_raw is None:
        return None
    return _PrecomputedSum.model_validate_json(result_raw)


async def _write_precomputed_sum_to_redis(
    itgs: Itgs, /, *, sum: _PrecomputedSum
) -> None:
    """Writes the given precomputed sum to redis. We don't expire this key as it
    is useful so long as this endpoint still exists, is very small, and without
    it the amount of time required to compute the total attributable users is
    uncapped.
    """
    redis = await itgs.redis()
    await redis.set(
        b"journey_share_links:total_attributable_users",
        sum.__pydantic_serializer__.to_json(sum),
    )


async def _count_attributable_users_from_redis(
    itgs: Itgs, /, *, start_unix_date_incl: int, end_unix_date_excl: int
) -> int:
    """Scans through the utm information in redis from the given
    start unix date (inclusive) to the given end unix date (exclusive),
    counting up how many users are attributable to the share link utm.

    This ignores the earliest key as its presumably already been checked.

    Regardless of how many dates are specified, or how many utms are specified,
    this will not result in blocking redis for an excessive period of time. However,
    the time this takes to run will primarily be linear to how many unique (utm, day)
    pairs we've seen in the given timerange
    """
    result: int = 0
    cursor1: int = 0
    cursor2: int = 0

    redis = await itgs.redis()
    await ensure_share_links_count_attributable_users_script_exists(redis, force=True)

    while True:
        res = await share_links_count_attributable_users(
            redis, start_unix_date_incl, end_unix_date_excl, cursor1, cursor2
        )
        assert res is not None
        cursor1 = res[0]
        cursor2 = res[1]
        result += res[2]

        if cursor1 == 0 and cursor2 == 0:
            return result


async def _count_attributable_users_from_db(
    itgs: Itgs,
    /,
    *,
    start_unix_date_incl: Optional[int],
    end_unix_date_excl: Optional[int],
):
    """Counts how many users can be attributed (via any click utm) to share links
    in the given timerange via the stats table in the database.
    """
    conn = await itgs.conn()
    cursor = conn.cursor("none")

    range_clause = ""
    range_args = []
    if start_unix_date_incl is not None:
        range_clause = "AND daily_utm_conversion_stats.retrieved_for >= ?"
        range_args.append(
            unix_dates.unix_date_to_date(start_unix_date_incl).isoformat()
        )

    if end_unix_date_excl is not None:
        if range_clause != "":
            range_clause += "\n            "

        range_clause += "AND daily_utm_conversion_stats.retrieved_for < ?"
        range_args.append(unix_dates.unix_date_to_date(end_unix_date_excl).isoformat())

    response = await cursor.execute(
        f"""
        SELECT
            SUM(holdover_any_click_signups) + SUM(any_click_signups)
        FROM daily_utm_conversion_stats, utms
        WHERE
            utms.id = daily_utm_conversion_stats.utm_id
            AND utms.utm_source = ?
            AND utms.utm_medium = ?
            AND utms.utm_campaign = ?
            {range_clause}
        """,
        (EXPECTED_UTM_SOURCE, EXPECTED_UTM_MEDIUM, EXPECTED_UTM_CAMPAIGN, *range_args),
    )
    if not response.results or response.results[0][0] is None:
        return 0

    result = response.results[0][0]
    assert isinstance(result, int)
    return result
