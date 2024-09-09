import asyncio
import gzip
import io
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Annotated, Optional, List, Union, cast
from content_files.lib.serve_s3_file import read_in_parts
from error_middleware import handle_error
from lifespan import lifespan_handler
from models import STANDARD_ERRORS_BY_CODE
from auth import auth_admin
from itgs import Itgs
from starlette.concurrency import run_in_threadpool
import perpetual_pub_sub as pps
import time
import unix_dates
import pytz
import datetime

router = APIRouter()


class TopSharer(BaseModel):
    sub: str = Field(description="The sub of the user")
    links_created: int = Field(description="The number of links created by the user")
    link_views_total: int = Field(
        description="The total number of views of all links created by the user"
    )
    link_views_unique: int = Field(
        description="The number of unique views of all links created by the user"
    )
    link_attributable_users: int = Field(
        description=(
            "The number of users who viewed a link created by this sharer and "
            "then later signed up"
        )
    )


class ReadTopSharersRequest(BaseModel):
    start_date: Optional[str] = Field(
        None,
        description="The start date of the time range (YYYY-MM-DD) to calculate top sharers for, "
        "or null for the beginning of time",
    )
    end_date: Optional[str] = Field(
        None,
        description="The end date of the time range (YYYY-MM-DD) to calculate top sharers for, "
        "or null for the latest possible",
    )


class ReadTopSharersResponse(BaseModel):
    top_sharers: List[TopSharer] = Field(
        description="The list of top sharers, sorted by link_views_total descending"
    )
    checked_at: float = Field(
        description="The timestamp at which the top sharers were calculated"
    )


@router.post(
    "/top_sharers",
    response_model=ReadTopSharersResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_top_sharers(
    args: ReadTopSharersRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    request_at = time.time()
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        request_date = unix_dates.unix_timestamp_to_unix_date(
            request_at, tz=pytz.timezone("America/Los_Angeles")
        )
        latest_available_date_excl = request_date - 1

        start_unix_date = (
            None
            if args.start_date is None
            else min(
                unix_dates.date_to_unix_date(
                    datetime.date.fromisoformat(args.start_date)
                ),
                latest_available_date_excl,
            )
        )
        end_unix_date = (
            latest_available_date_excl
            if args.end_date is None
            else min(
                unix_dates.date_to_unix_date(
                    datetime.date.fromisoformat(args.end_date)
                ),
                latest_available_date_excl,
            )
        )

        if start_unix_date is not None and start_unix_date >= end_unix_date:
            return Response(
                content=ReadTopSharersResponse(
                    top_sharers=[], checked_at=request_at
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=200,
            )

        return await get_or_initialize_top_sharers(
            itgs,
            request_at=request_at,
            start_unix_date=start_unix_date,
            end_unix_date=end_unix_date,
        )


async def get_or_initialize_top_sharers(
    itgs: Itgs,
    /,
    *,
    request_at: float,
    start_unix_date: Optional[int],
    end_unix_date: int,
) -> Response:
    result = await _read_top_sharers_from_local_cache(
        itgs, start_unix_date, end_unix_date
    )
    if result is not None:
        return result

    result_bytes = await _read_top_sharers_from_redis(
        itgs, start_unix_date, end_unix_date
    )
    if result_bytes is not None:
        await _write_top_sharers_to_local_cache(
            itgs, start_unix_date, end_unix_date, result_bytes
        )
        return Response(
            content=result_bytes,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Content-Encoding": "gzip",
            },
            status_code=200,
        )

    result_typed = await _read_top_sharers_from_database(
        itgs,
        request_at=request_at,
        start_unix_date=start_unix_date,
        end_unix_date=end_unix_date,
    )
    result_bytes = await _serialize_and_compress(result_typed)
    await _write_top_sharers_to_local_cache(
        itgs, start_unix_date, end_unix_date, result_bytes
    )
    await _push_top_sharers_to_all_local_caches(
        itgs, start_unix_date, end_unix_date, result_bytes
    )
    await _write_top_sharers_to_redis(
        itgs, start_unix_date, end_unix_date, result_bytes
    )
    return Response(
        content=result_bytes,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Content-Encoding": "gzip",
        },
        status_code=200,
    )


async def _read_top_sharers_from_local_cache(
    itgs: Itgs, start_unix_date: Optional[int], end_unix_date: int
) -> Optional[Response]:
    """Reads the serialized and compressed ReadTopSharersResponse from the local cache,
    streaming if appropriate, if it's available. Otherwise, returns None
    """
    cache = await itgs.local_cache()
    raw = cast(
        Union[bytes, io.BytesIO, None],
        cache.get(f"journey_share_links:top_sharers:{start_unix_date}:{end_unix_date}"),
    )
    if raw is None:
        return None

    if isinstance(raw, (bytes, bytearray, memoryview)):
        return Response(
            content=raw[8:],
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Content-Encoding": "gzip",
            },
            status_code=200,
        )

    content_length = int.from_bytes(raw.read(8), "big", signed=False)
    return Response(
        content=read_in_parts(raw),
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Content-Encoding": "gzip",
            "Content-Length": str(content_length),
        },
        status_code=200,
    )


async def _write_top_sharers_to_local_cache(
    itgs: Itgs, start_unix_date: Optional[int], end_unix_date: int, top_sharers: bytes
) -> None:
    """Writes the given serialized and compressed ReadTopSharersResponse to the local
    cache.
    """
    cache = await itgs.local_cache()
    cache.set(
        f"journey_share_links:top_sharers:{start_unix_date}:{end_unix_date}".encode("utf-8"),  # type: ignore
        len(top_sharers).to_bytes(8, "big", signed=False) + top_sharers,
        expire=60 * 60 * 2,
    )


async def _read_top_sharers_from_redis(
    itgs: Itgs, start_unix_date: Optional[int], end_unix_date: int
) -> Optional[bytes]:
    """Reads the serialized and compressed ReadTopSharersResponse from redis, if it's
    available. Otherwise, returns None
    """
    redis = await itgs.redis()
    return await redis.get(
        f"journey_share_links:top_sharers:{start_unix_date}:{end_unix_date}".encode("utf-8")  # type: ignore
    )


async def _write_top_sharers_to_redis(
    itgs: Itgs, start_unix_date: Optional[int], end_unix_date: int, top_sharers: bytes
) -> None:
    """Writes the given serialized and compressed ReadTopSharersResponse to redis."""
    redis = await itgs.redis()
    await redis.set(
        f"journey_share_links:top_sharers:{start_unix_date}:{end_unix_date}".encode("utf-8"),  # type: ignore
        top_sharers,
        ex=60 * 60 * 2,
    )


async def _push_top_sharers_to_all_local_caches(
    itgs: Itgs, start_unix_date: Optional[int], end_unix_date: int, top_sharers: bytes
) -> None:
    """Pushes the given serialized and compressed ReadTopSharersResponse to all local
    caches. This is done in a fire-and-forget manner.
    """
    message = (
        (
            b"\xff\xff\xff\xff"
            if start_unix_date is None
            else start_unix_date.to_bytes(4, "big", signed=False)
        )
        + end_unix_date.to_bytes(4, "big", signed=False)
        + len(top_sharers).to_bytes(8, "big", signed=False)
        + top_sharers
    )

    redis = await itgs.redis()
    await redis.publish("ps:journey_share_links:top_sharers", message)


async def _read_top_sharers_from_database(
    itgs: Itgs,
    /,
    *,
    request_at: float,
    start_unix_date: Optional[int],
    end_unix_date: int,
) -> ReadTopSharersResponse:
    conn = await itgs.conn()
    cursor = conn.cursor("none")

    tz = pytz.timezone("America/Los_Angeles")
    start_unix = (
        unix_dates.unix_date_to_timestamp(start_unix_date, tz=tz)
        if start_unix_date is not None
        else None
    )
    end_unix = unix_dates.unix_date_to_timestamp(end_unix_date, tz=tz)

    response = await cursor.execute(
        """
WITH users_with_views(user_id, views) AS (
SELECT
    journey_share_links.user_id,
    COUNT(*)
FROM journey_share_link_views, journey_share_links
WHERE
    journey_share_link_views.journey_share_link_id = journey_share_links.id
    AND (? IS NULL OR journey_share_link_views.created_at >= ?)
    AND journey_share_link_views.created_at < ?
    AND journey_share_links.user_id IS NOT NULL
GROUP BY journey_share_links.user_id
), users_with_num_links(user_id, num_links) AS (
SELECT
    journey_share_links.user_id,
    COUNT(*)
FROM journey_share_links
WHERE
    journey_share_links.user_id IS NOT NULL
    AND (? IS NULL OR journey_share_links.created_at >= ?)
    AND journey_share_links.created_at < ?
GROUP BY journey_share_links.user_id
), users_with_unique_views(user_id, unique_views) AS (
SELECT
    journey_share_links.user_id,
    COUNT(*)
FROM journey_share_link_views, journey_share_links
WHERE
    journey_share_link_views.journey_share_link_id = journey_share_links.id
    AND (? IS NULL OR journey_share_link_views.created_at >= ?)
    AND journey_share_link_views.created_at < ?
    AND journey_share_links.user_id IS NOT NULL
    AND journey_share_link_views.visitor_was_unique
GROUP BY journey_share_links.user_id
), users_with_attributable_users(user_id, attributable_users) AS (
SELECT
    journey_share_links.user_id,
    COUNT(*)
FROM journey_share_links, users AS attributed_users
WHERE
    journey_share_links.user_id IS NOT NULL
    AND EXISTS (
        SELECT 1 FROM journey_share_link_views
        WHERE
            journey_share_link_views.journey_share_link_id = journey_share_links.id
            AND (? IS NULL OR journey_share_link_views.created_at >= ?)
            AND journey_share_link_views.created_at < ?
            AND journey_share_link_views.user_id = attributed_users.id
            AND journey_share_link_views.created_at < attributed_users.created_at
    )
GROUP BY journey_share_links.user_id
)
SELECT
    users.sub,
    COALESCE(users_with_num_links.num_links, 0),
    users_with_views.views,
    COALESCE(users_with_unique_views.unique_views, 0),
    COALESCE(users_with_attributable_users.attributable_users, 0)
FROM users_with_views, users
LEFT OUTER JOIN users_with_num_links ON (
    users_with_num_links.user_id = users.id
)
LEFT OUTER JOIN users_with_unique_views ON (
    users_with_unique_views.user_id = users.id
)
LEFT OUTER JOIN users_with_attributable_users ON (
    users_with_attributable_users.user_id = users.id
)
WHERE
    users_with_views.user_id = users.id
    AND users_with_views.views > 0
ORDER BY users_with_views.views DESC
LIMIT 10
        """,
        [start_unix, start_unix, end_unix] * 4,
    )

    top_sharers: List[TopSharer] = []
    for row in response.results or []:
        top_sharers.append(
            TopSharer(
                sub=row[0],
                links_created=row[1],
                link_views_total=row[2],
                link_views_unique=row[3],
                link_attributable_users=row[4],
            )
        )

    return ReadTopSharersResponse(top_sharers=top_sharers, checked_at=request_at)


async def _serialize_and_compress(top_sharers: ReadTopSharersResponse) -> bytes:
    return await run_in_threadpool(_serialize_and_compress_sync, top_sharers)


def _serialize_and_compress_sync(raw: ReadTopSharersResponse) -> bytes:
    return gzip.compress(raw.__pydantic_serializer__.to_json(raw), mtime=0)


async def handle_incoming_top_sharers_loop():
    assert pps.instance is not None

    try:
        async with pps.PPSSubscription(
            pps.instance, "ps:journey_share_links:top_sharers", "jsl_rts_hitsl"
        ) as sub:
            async for message_raw in sub:
                message = io.BytesIO(message_raw)
                start_unix_date_bytes = message.read(4)
                if start_unix_date_bytes == b"\xff\xff\xff\xff":
                    start_unix_date = None
                else:
                    start_unix_date = int.from_bytes(
                        start_unix_date_bytes, "big", signed=False
                    )

                end_unix_date = int.from_bytes(message.read(4), "big", signed=False)
                payload_length = int.from_bytes(message.read(8), "big", signed=False)
                payload_raw = message.read(payload_length)

                async with Itgs() as itgs:
                    await _write_top_sharers_to_local_cache(
                        itgs, start_unix_date, end_unix_date, payload_raw
                    )
    except Exception as e:
        if pps.instance.exit_event.is_set() and isinstance(e, pps.PPSShutdownException):
            return  # type: ignore
        await handle_error(e)
    finally:
        print(
            "admin.journey_share_links.routes.read_top_sharers#handle_incoming_top_sharers_loop exiting"
        )


@lifespan_handler
async def register_background_tasks():
    task = asyncio.create_task(handle_incoming_top_sharers_loop())
    yield
