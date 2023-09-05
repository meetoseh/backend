import asyncio
from dataclasses import dataclass
import datetime
import gzip
import json
import time
from typing import Callable, Coroutine, Dict, List, Optional, Tuple, Type, Union
from fastapi.concurrency import run_in_threadpool

from fastapi.responses import StreamingResponse
from auth import auth_admin
from content_files.lib.serve_s3_file import read_in_parts
from error_middleware import handle_error

from itgs import Itgs

try:
    from typing import Never
except ImportError:
    from typing import NoReturn as Never

from fastapi import Response
from pydantic import BaseModel
import io
import itertools
import unix_dates
import pytz
import perpetual_pub_sub as pps


@dataclass
class ReadDailyStatsRouteArgs:
    """The various parts of a daily stats route constructed via
    create_daily_stats_route
    """

    table_name: Optional[str]
    """The name of the table which contains the statistics, for
    example, `sms_send_stats`. This table must contain the fields
    `id`, `retrieved_for`, and `retrieved_at`. The remaining fields
    are all number-valued with an optional pair that has the same
    name with `_breakdown` that is a string-valued field containing
    a json object whose keys are strings and values are numbers.

    Example:

    ```sql
    CREATE TABLE my_daily_stats (
        id INTEGER PRIMARY KEY,
        retrieved_for TEXT UNIQUE NOT NULL,
        retrieved_at REAL NOT NULL,
        my_basic_stat INTEGER NOT NULL,
        my_fancy_stat INTEGER NOT NULL,
        my_fancy_stat_breakdown TEXT NOT NULL
    );
    INSERT INTO my_daily_stats (
        retrieved_for, 
        retrieved_at, 
        my_basic_stat, 
        my_fancy_stat, 
        my_fancy_stat_breakdown
    ) VALUES (
        '2023-08-31',
        1693572300.3936846,
        5,
        10,
        '{"a": 6, "b": 4}'
    )
    ```

    Note how `retrieved_for` is the isoformatted date, where dates are
    broken using the America/Los_Angeles timezone, and `retrieved_at`
    is unix time in seconds.

    May be None to only generate a partial route, where the historical
    route simply returns 404
    """

    basic_data_redis_key: Callable[[int], bytes]
    """A function which accepts a unix date and returns the redis key
    where the basic data would be contained. This key should correspond
    to a hash where the keys are just the same as number-valued fields
    in the table, including the fancy keys but not their breakdowns.
    Continuing the example of `my_daily_stats`, this would be something
    like `lambda unix_date: f"stats:mine:daily:{unix_date}".encode("ascii")` and the keys
    would be `my_basic_stat` and `my_fancy_stat`, both of which go to
    numbers.
    """

    extra_data_redis_key: Optional[Callable[[int, str], bytes]]
    """A function which accepts a unix date and a key and returns the
    redis key where the extra data would be contained. The resulting
    key should correspond to a hash where the keys are arbitrary strings
    (though they should be explained in the documentation) and the values
    are numbers. Continuing the example, this would be
    `lambda unix_date, key: f"stats:mine:daily:{unix_date}:extra:{key}".encode("ascii")`
    and the only acceptable key argument would be `my_fancy_stat`

    The numbers within this key should sum to the same value as the
    value in the basic data, since it's meant to further subdivide the
    event.

    May be omitted iff there are no fancy fields
    """

    earliest_data_redis_key: bytes
    """The key which contains the earliest unix date for which there
    might be data still in redis. For example, `b"stats:mine:daily:earliest"`.
    This avoids having to check the database to determine if the data has
    been rolled over yet.
    """

    pubsub_redis_key: Optional[bytes]
    """The pub/sub redis key that we can use to coordinate instances cached
    values. For example, `b"ps:stats:mine:daily"`. May be omitted iff the
    table_name is None.
    """

    compressed_response_local_cache_key: Optional[Callable[[int, int], bytes]]
    """The key in the local cache where we can store the compressed
    response for the given start (inclusive) and end (exclusive) unix
    date range.

    May be omitted iff the table_name is None.
    """

    simple_fields: List[str]
    """The names of the simple fields, i.e., fields without breakdowns."""

    fancy_fields: List[str]
    """The names of the fancy fields, i.e., fields with breakdowns."""

    response_model: Optional[Type[BaseModel]]
    """The model which can be passed the fields and produces the response
    model for the historical data endpoint. For example,

    ```py
    class MyResponse(BaseModel):
        labels: List[str] = Field(description="the labels for each item in all the lists, index-correspondant")
        my_basic_stat: List[int] = Field(description="An example basic stat")
        my_fancy_stat: List[int] = Field(description="An example fancy stat")
        my_fancy_stat_breakdown: Dict[str, List[int]] = Field(
            description="My fancy stat broken down by letter, each by day"
        )
    ```

    May be omitted iff the table_name is None.
    """

    partial_response_model: Type[BaseModel]
    """The model which can be passed todays and yesterdays data and produces
    the response model for the partial data endpoint, i.e., the endpoint the
    frontend uses to get the data that may not have been rotated to the database
    yet as it might still be changing. For example,

    ```py
    class MyPartialResponseItem(BaseModel):
        my_basic_stat: int = Field(0)
        my_fancy_stat: int = Field(0)
        my_fancy_stat_breakdown: Dict[str, int] = Field(default_factory=dict)
    
    class MyPartialResponse(BaseModel):
        today: MyPartialResponseItem = Field()
        yesterday: MyPartialResponseItem = Field()
    ```

    The item model default values must be set, i.e., each field should be optional
    in the constructor.
    
    The response route should explain in its documentation to defer to the full
    data endpoint for an explanation of the fields.
    """


@dataclass
class ReadDailyStatsRouteResult:
    handler: Callable[[Optional[str]], Coroutine[None, None, Response]]
    """The callable which accepts the authorization header and forms the
    historical data endpoint response.
    """

    partial_handler: Callable[[Optional[str]], Coroutine[None, None, Response]]
    """The callable which accepts the authorization header and forms the
    partial data endpoint response.
    """

    background_task: Callable[[], Coroutine[None, None, Never]]
    """The background task that must be registered in the main
    background tasks in order to improve performance. This task
    is used for coordinating the multiple instances to avoid them
    all needed to create the same compressed response when that
    response is cacheable.
    """


def create_daily_stats_route(args: ReadDailyStatsRouteArgs):
    """Convenience function for constructing the two routes required for
    exposing a daily chart to the frontend. The first endpoint contains
    the bulk of the data and contains the historical, unchanging, cacheable
    part. The second endpoint contains just the last two days of data, i.e.,
    the recent and uncacheable part.

    For some endpoints yesterdays data is also cacheable, which implies that
    data is never backdated. Since backdating can be very convenient for
    making the data more human interpretable, and is infectious, this always
    constructs the routes so that they do not have to be changed if backdating
    is added, even if it's not necessary.

    An example of why you might backdate: suppose you are trying to track that
    the producers and consumers of a queue are balanced, i.e., all the items
    queued were eventually processed. There is a time delay for consuming the
    items, so if you increment the `queue` event at the time the item was
    queued, and `consume` event at the time the item was consumed, and the
    day rolls over between the two, you'd get two days data like so:

    - day 1: `{"queue": 1, "consume": 0}`
    - day 2: `{"queue": 0, "consume": 1}`

    Although it appears obvious what happened here, it gets way less obvious
    when the crossovers only make up a very small percent, making an error more
    believable. Here's a valid result where nothing went wrong:

    - day 1: `{"queue": 567899, "consume": 567897}`
    - day 2: `{"queue": 487777, "consume": 487777}`
    - day 3: `{"queue": 540033, "consume": 540035}`

    Note that in this case day 1 and 2 had 2 bleed over. This chain of bleedovers
    could continue forever and slowly increase, making it very hard to interpet.
    By backdating the consume event to occur at the same timestamp as the queue
    event, now yesterdays data can still change today (hence is not cachable),
    but the two values should always match, which is much simpler to verify.

    NOTE:
        This is a pure function. The caller must actually register the
        appropriate routes and background handler.

    PERF:
        This will generally be faster than constructing the routes by hand
        when using the same technique, as it performs some optimizations that
        would not make sense when constructing the source code by hand, such
        as reduced unnecessary whitespace in the sql and aliasing the fields to
        reduce response sizes.

    Args:
        args (ReadDailyStatsRouteArgs): The data used to construct the route

    Returns:
        ReadDailyStatsRouteResult: The result of the route construction, which
            can be used to trivially implement the two routes and register the
            background task.
    """
    assert len(args.simple_fields) + len(args.fancy_fields) > 0
    # easy mistake to make is str keys instead of bytes, but that changes how
    # our redis client behaves in an undesirable way
    assert isinstance(args.basic_data_redis_key(0), bytes)
    if args.fancy_fields:
        assert isinstance(args.extra_data_redis_key(0, ""), bytes)
    else:
        assert args.extra_data_redis_key is None
    assert isinstance(args.earliest_data_redis_key, bytes)
    if args.table_name is not None:
        assert isinstance(args.pubsub_redis_key, bytes)
    else:
        assert args.pubsub_redis_key is None
    # similarly, we want to be consistent with accessing the local cache via bytes keys
    if args.table_name is not None:
        assert isinstance(args.compressed_response_local_cache_key(0, 0), bytes)
    else:
        assert args.compressed_response_local_cache_key is None

    # Other consistency things
    if args.table_name is not None:
        assert args.response_model is not None
    else:
        assert args.response_model is None

    historical_handler, background_task = _create_historical(args)
    partial_handler = _create_partial(args)

    return ReadDailyStatsRouteResult(
        handler=historical_handler,
        partial_handler=partial_handler,
        background_task=background_task,
    )


def _create_historical(
    args: ReadDailyStatsRouteArgs,
) -> Tuple[
    Callable[[Optional[str]], Coroutine[None, None, Response]],
    Callable[[], Coroutine[None, None, Never]],
]:
    if args.table_name is None:

        async def _void_handler(authorization: Optional[str]) -> Response:
            return Response(status_code=404)

        async def _void_background_task() -> Never:
            return

        return _void_handler, _void_background_task

    read_from_source_sql = _create_read_from_source_sql(args)
    num_simple_lists = len(args.simple_fields) + len(args.fancy_fields)
    tz = pytz.timezone("America/Los_Angeles")

    async def read_from_source(
        itgs: Itgs, *, start_unix_date: int, end_unix_date: int
    ) -> BaseModel:
        """start inclusive, end exclusive"""
        conn = await itgs.conn()
        cursor = conn.cursor("none")
        response = await cursor.execute(
            read_from_source_sql,
            (
                unix_dates.unix_date_to_date(start_unix_date).isoformat(),
                unix_dates.unix_date_to_date(end_unix_date).isoformat(),
            ),
        )

        labels: List[str] = []
        simple_lists: List[List[int]] = [list() for _ in range(num_simple_lists)]
        breakdown_lists: List[Dict[str, List[int]]] = [
            dict() for _ in range(len(args.fancy_fields))
        ]

        def push_empty_day(date: int):
            labels.append(unix_dates.unix_date_to_date(date).isoformat())
            for lst in simple_lists:
                lst.append(0)
            for extra in breakdown_lists:
                for lst in extra.values():
                    lst.append(0)

        next_unix_date = start_unix_date
        for row in response.results or []:
            row_retrieved_for_unix_date = unix_dates.date_to_unix_date(
                datetime.date.fromisoformat(row[0])
            )

            while next_unix_date < row_retrieved_for_unix_date:
                push_empty_day(next_unix_date)
                next_unix_date += 1

            labels.append(row[0])

            for idx in range(num_simple_lists):
                simple_lists[idx].append(row[idx + 1])
            for idx in range(
                num_simple_lists, num_simple_lists + len(args.fancy_fields)
            ):
                to_add: Dict[str, int] = json.loads(row[idx + 1])
                dict_of_lists = breakdown_lists[idx - num_simple_lists]
                for key, val in to_add.items():
                    arr = dict_of_lists.get(key)
                    if arr is None:
                        arr = [0] * (next_unix_date - start_unix_date)
                        dict_of_lists[key] = arr
                    arr.append(val)
            next_unix_date += 1

        while next_unix_date < end_unix_date:
            push_empty_day(next_unix_date)
            next_unix_date += 1

        response_obj = dict()
        response_obj["labels"] = labels
        for idx, field in enumerate(args.simple_fields):
            response_obj[field] = simple_lists[idx]
        for idx, field in enumerate(args.fancy_fields):
            response_obj[field] = simple_lists[idx + len(args.simple_fields)]
            response_obj[field + "_breakdown"] = breakdown_lists[idx]

        return args.response_model.parse_obj(response_obj)

    async def read_from_cache(
        itgs: Itgs, *, start_unix_date: int, end_unix_date: int
    ) -> Union[bytes, io.BytesIO, None]:
        cache = await itgs.local_cache()
        key = args.compressed_response_local_cache_key(start_unix_date, end_unix_date)
        return cache.get(key, read=True)

    def serialize_and_compress(raw: BaseModel) -> bytes:
        # brotli would probably be better but not built-in
        return gzip.compress(raw.json().encode("utf-8"), mtime=0)

    async def write_to_cache(
        itgs: Itgs, *, start_unix_date: int, end_unix_date: int, data: bytes
    ) -> None:
        now = time.time()
        tomorrow_unix_date = unix_dates.unix_timestamp_to_unix_date(now, tz=tz) + 1
        cache_expire_in = (
            unix_dates.unix_date_to_timestamp(tomorrow_unix_date, tz=tz) - now
        )
        if cache_expire_in > 0:
            cache = await itgs.local_cache()
            key = args.compressed_response_local_cache_key(
                start_unix_date, end_unix_date
            )
            cache.set(key, data, expire=cache_expire_in)

    async def write_to_other_instances(
        itgs: Itgs, *, start_unix_date: int, end_unix_date: int, data: bytes
    ) -> None:
        redis = await itgs.redis()
        message = (
            int.to_bytes(start_unix_date, 4, "big", signed=False)
            + int.to_bytes(end_unix_date, 4, "big", signed=False)
            + len(data).to_bytes(8, "big", signed=False)
            + data
        )
        await redis.publish(args.pubsub_redis_key, message)

    async def read_from_other_instances() -> Never:
        try:
            async with pps.PPSSubscription(
                pps.instance,
                args.pubsub_redis_key.decode("utf-8"),
                f"read_daily_stats-{args.table_name}",
            ) as sub:
                async for raw_message_bytes in sub:
                    msg = io.BytesIO(raw_message_bytes)
                    start_unix_date = int.from_bytes(msg.read(4), "big", signed=False)
                    end_unix_date = int.from_bytes(msg.read(4), "big", signed=False)
                    data_len = int.from_bytes(msg.read(8), "big", signed=False)
                    data = msg.read(data_len)

                    async with Itgs() as itgs:
                        await write_to_cache(
                            itgs,
                            start_unix_date=start_unix_date,
                            end_unix_date=end_unix_date,
                            data=data,
                        )
        except Exception as e:
            if pps.instance.exit_event.is_set() and isinstance(
                e, pps.PPSShutdownException
            ):
                return
            await handle_error(e)
        finally:
            print(
                f"admin.lib.read_daily_stats#background_task for {args.table_name} exiting"
            )

    async def handler(authorization: Optional[str]) -> Response:
        async with Itgs() as itgs:
            auth_result = await auth_admin(itgs, authorization)
            if not auth_result.success:
                return auth_result.error_response

            today_unix_date = unix_dates.unix_date_today(tz=tz)
            end_unix_date = today_unix_date - 1
            start_unix_date = end_unix_date - 90

            cachable_until = unix_dates.unix_date_to_timestamp(
                today_unix_date + 1, tz=tz
            )
            cache_expires_in = int(cachable_until - time.time())
            if cache_expires_in <= 0:
                cache_expires_in = 60

            headers = {
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": f"private, max-age={cache_expires_in}, stale-if-error=600",
                "Content-Encoding": "gzip",
            }

            cached_result = await read_from_cache(
                itgs, start_unix_date=start_unix_date, end_unix_date=end_unix_date
            )
            if cached_result is not None:
                if isinstance(cached_result, (bytes, bytearray)):
                    return Response(content=cached_result, headers=headers)
                return StreamingResponse(
                    content=read_in_parts(cached_result), headers=headers
                )

            typed_response = await read_from_source(
                itgs, start_unix_date=start_unix_date, end_unix_date=end_unix_date
            )
            result = await run_in_threadpool(serialize_and_compress, typed_response)
            await write_to_cache(
                itgs,
                start_unix_date=start_unix_date,
                end_unix_date=end_unix_date,
                data=result,
            )
            await write_to_other_instances(
                itgs,
                start_unix_date=start_unix_date,
                end_unix_date=end_unix_date,
                data=result,
            )
            return Response(content=result, headers=headers)

    return handler, read_from_other_instances


def _create_partial(
    args: ReadDailyStatsRouteArgs,
) -> Callable[[Optional[str]], Coroutine[None, None, Response]]:
    read_from_db_sql: Optional[str] = None
    tz = pytz.timezone("America/Los_Angeles")

    async def read_from_db(
        itgs: Itgs, *, unix_date: int
    ) -> Dict[str, Union[int, Dict[str, int]]]:
        nonlocal read_from_db_sql

        if args.table_name is None:
            return dict()

        if read_from_db_sql is None:
            read_from_db_sql = _create_read_partial_from_db_sql(args)

        conn = await itgs.conn()
        cursor = conn.cursor("none")

        response = await cursor.execute(
            read_from_db_sql,
            (unix_dates.unix_date_to_date(unix_date).isoformat(),),
        )

        if not response.results:
            return dict()

        row = response.results[0]
        result = dict()

        for idx, field in enumerate(args.simple_fields):
            result[field] = row[idx]
        for idx, field in enumerate(args.fancy_fields):
            result[field] = row[len(args.simple_fields) + idx]
        for idx, field in enumerate(args.fancy_fields):
            result[field + "_breakdown"] = json.loads(
                row[len(args.simple_fields) + len(args.fancy_fields) + idx]
            )

        return result

    async def read_from_redis(
        itgs: Itgs, *, unix_dates: List[int]
    ) -> List[Optional[Dict[str, Union[int, Dict[str, int]]]]]:
        redis = await itgs.redis()

        async with redis.pipeline(transaction=False) as pipe:
            await pipe.get(args.earliest_data_redis_key)
            for unix_date in unix_dates:
                await pipe.hgetall(args.basic_data_redis_key(unix_date))
                for field in args.fancy_fields:
                    await pipe.hgetall(args.extra_data_redis_key(unix_date, field))
            results = await pipe.execute()

        if results[0] is None:
            return [None] * len(unix_dates)

        earliest_date = int(results[0])

        parsed_results = []
        results_idx = 1
        for unix_date in unix_dates:
            if unix_date < earliest_date:
                results_idx += 1 + len(args.fancy_fields)
                parsed_results.append(None)
                continue

            basic_data: List[Tuple[bytes, bytes]] = results[results_idx]
            fancy_data: List[List[Tuple[bytes, bytes]]] = results[
                results_idx + 1 : results_idx + 1 + len(args.fancy_fields)
            ]
            results_idx += 1 + len(args.fancy_fields)

            merged_data = dict(
                (key.decode("utf-8"), int(val)) for key, val in basic_data
            )
            for field, data in zip(args.fancy_fields, fancy_data):
                merged_data[field + "_breakdown"] = dict(
                    (key.decode("utf-8"), int(val)) for key, val in data
                )
            parsed_results.append(merged_data)
        return parsed_results

    async def handler(authorization: Optional[str]) -> Response:
        async with Itgs() as itgs:
            auth_result = await auth_admin(itgs, authorization)
            if not auth_result.success:
                return auth_result.error_response

            today_unix_date = unix_dates.unix_date_today(tz=tz)
            yesterday_unix_date = today_unix_date - 1

            response_obj_items = await read_from_redis(
                itgs, unix_dates=[yesterday_unix_date, today_unix_date]
            )
            for idx, (unix_date, response_obj_item) in enumerate(
                zip([yesterday_unix_date, today_unix_date], response_obj_items)
            ):
                if response_obj_item is None:
                    response_obj_items[idx] = await read_from_db(
                        itgs, unix_date=unix_date
                    )

            response_obj = {
                "yesterday": response_obj_items[0],
                "today": response_obj_items[1],
            }

            response_content = args.partial_response_model.parse_obj(response_obj)
            return Response(
                content=response_content.json(),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Cache-Control": "no-store",
                },
                status_code=200,
            )

    return handler


def _create_read_from_source_sql(args: ReadDailyStatsRouteArgs) -> str:
    builder = io.StringIO()
    builder.write('SELECT "retrieved_for" AS "a0"')

    idx = 1

    def make_alias():
        letter_offset = idx % 26
        number_offset = idx // 26
        return chr(ord("a") + letter_offset) + str(number_offset)  # e.g., a0

    for field in itertools.chain(args.simple_fields, args.fancy_fields):
        builder.write(", ")
        builder.write('"')
        builder.write(field)
        builder.write('" AS ')
        builder.write(make_alias())

        idx += 1

    for field in args.fancy_fields:
        builder.write(', "')
        builder.write(field)
        builder.write('_breakdown" AS ')
        builder.write(make_alias())

        idx += 1

    builder.write(' FROM "')
    builder.write(args.table_name)
    builder.write(
        '" WHERE retrieved_for >= ? AND retrieved_for < ? ORDER BY retrieved_for ASC'
    )
    return builder.getvalue()


def _create_read_partial_from_db_sql(args: ReadDailyStatsRouteArgs) -> str:
    builder = io.StringIO()
    builder.write("SELECT ")

    idx = 0

    def make_alias():
        letter_offset = idx % 26
        number_offset = idx // 26
        return chr(ord("a") + letter_offset) + str(number_offset)  # e.g., a0

    for field in itertools.chain(args.simple_fields, args.fancy_fields):
        if idx != 0:
            builder.write(", ")

        builder.write('"')
        builder.write(field)
        builder.write('" AS ')
        builder.write(make_alias())

        idx += 1

    for field in args.fancy_fields:
        builder.write(', "')
        builder.write(field)
        builder.write('_breakdown" AS ')
        builder.write(make_alias())

        idx += 1

    builder.write(' FROM "')
    builder.write(args.table_name)
    builder.write('" WHERE retrieved_for = ?')
    return builder.getvalue()
