from itgs import Itgs
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from typing import (
    Callable,
    Dict,
    Generator,
    List,
    NoReturn,
    Optional,
    Set,
    Tuple,
    Union,
)
from daily_events.models.external_daily_event import (
    ExternalDailyEvent,
    ExternalDailyEventAccess,
    ExternalDailyEventJourney,
    ExternalDailyEventJourneyAccess,
    ExternalDailyEventJourneyCategory,
    ExternalDailyEventJourneyDescription,
    ExternalDailyEventJourneyInstructor,
)
from daily_events.auth import DailyEventLevel
import daily_events.auth
import perpetual_pub_sub as pps
import diskcache
import asyncio
import random
import time
import io


ALL_LEVELS: List[str] = ("read,start_full", "read,start_random", "read,start_one")
"""All the levels we actually use, so that we can evict all the caches when
necessary
"""

cache_received_listeners: Dict[
    Tuple[str, str], List[Callable[[str, str, int, bytes], None]]
] = dict()
"""A mapping from (daily_event_uid, level) to a list of listeners to call when
the cached representation of the daily event with the given uid is received.

Each callable is passed (uid, level, jwt_insert_index, serialized_without_jwt)
and will have already been removed from the list of listeners before being called,
meaning if it wants to be called again it must re-register itself.

Typically these callables will be used to set asyncio events, though they can
do anything. They are called from the main thread, so they should not block
and can interact with the event loop

To avoid a memory leak, listeners should be removed when they are no longer
needed.
"""

HEADERS = {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
}
"""The headers we return on success"""


async def read_one_external(
    itgs: Itgs, *, uid: str, level: Set[DailyEventLevel]
) -> Optional[Response]:
    """Fetches the daily event with the given uid and returns it in the format
    that we would expose to an end-user. This format includes a JWT to use to
    take further actions with the daily event, without having to check every
    possible reason they may have access to it. That JWT will be granted the
    levels selected here, and those levels will be converted into a more
    client-friendly format via the `access` fields of the response.

    Note that although a JWT can be used to avoid network traffic, some of the
    permissions, e.g., `start_one`, are implemented via a combination of
    revoking the JWT once it's used and by checking that a different JWT hasn't
    already been used for that purpose for the same user. These, obviously,
    require network traffic.

    The JWT is still serving a purpose however: primarily, we don't want the
    endpoint that handles starting a random journey to know that the user has
    access because of a referral vs the pro entitlement vs some other reason.

    Since this is part of the critical path, this uses a cache with automatic
    cache invalidation/propagation to reduce load on the database. Hence, some
    of the serialization can often be skipped, which is why this returns a
    response object directly, which is already serialized, rather than an
    ExternalDailyEvent object directly. In the right circumstances, the returned
    response may be a StreamingResponse as it may not be necessary to load the
    entire response into memory to produce it.

    Args:
        itgs (Itgs): The integrations to (re)use uid (str): The uid of the daily
        event to fetch level (Set[DailyEventLevel]): The levels of access to
        grant the JWT

    Returns:
        (ExternalDailyEvent, None): The daily event, with a JWT to use to access
            it, if found, otherwise None

    Raises:
        AssertionError: if `level` does not at least include the `read` level
    """
    level_comma_sep = ",".join(sorted(level))
    if level_comma_sep not in ALL_LEVELS:
        raise ValueError(
            f"Invalid level: {level_comma_sep}, expected one of {ALL_LEVELS}"
        )

    jwt = await daily_events.auth.create_jwt(itgs, daily_event_uid=uid, level=level)

    local_cache = await itgs.local_cache()
    result_gen = get_locally_cached(
        local_cache, uid=uid, level=level_comma_sep, jwt=jwt
    )
    have_local_cache = next(result_gen)
    if have_local_cache:
        return StreamingResponse(
            content=result_gen,
            headers=HEADERS,
        )

    # we haven't yielded control of the main thread since we checked the local
    # cache here, so we're still safe to register a listener for the cache
    # without racing. however we can't wait until we check if we've got the
    # lock, since we'd have a race condition

    jwt_insert_index: Optional[int] = None
    serialized_without_jwt: Optional[bytes] = None
    cache_received_event: asyncio.Event = asyncio.Event()

    def on_cache_recieved(
        _: str, __: str, new_jwt_insert_index: int, new_serialized_without_jwt: bytes
    ):
        nonlocal jwt_insert_index
        nonlocal serialized_without_jwt

        jwt_insert_index = new_jwt_insert_index
        serialized_without_jwt = new_serialized_without_jwt

        cache_received_event.set()

    key = (uid, level_comma_sep)
    if key not in cache_received_listeners:
        cache_received_listeners[key] = [on_cache_recieved]
    else:
        cache_received_listeners[key].append(on_cache_recieved)

    redis = await itgs.redis()
    lock_key = f"daily_events:external:cache_lock:{uid}:{level_comma_sep}"
    took_lock = await redis.setnx(lock_key, "1")
    if not took_lock:
        try:
            await asyncio.wait_for(
                cache_received_event.wait(), timeout=1 + random.random()
            )
            assert isinstance(jwt_insert_index, int)
            assert isinstance(serialized_without_jwt, (bytes, bytearray, memoryview))
            result_gen = _inject_jwt(
                io.BytesIO(serialized_without_jwt), jwt_insert_index, jwt
            )
            return StreamingResponse(content=result_gen, headers=HEADERS)
        except asyncio.TimeoutError:
            slack = await itgs.slack()
            await slack.send_web_error_message(
                "daily_events.lib.read_one_external: Timeout waiting for cache_received_event"
            )

            # fall down to as if we took the lock

    try:
        event_without_jwt = await read_one_external_from_db(itgs, uid=uid, level=level)
        if event_without_jwt is None:
            return None

        serialized_without_jwt = event_without_jwt.json().encode("utf-8")
        jwt_insert_index = serialized_without_jwt.index(b'"jwt": ""') + len('"jwt": "')

        set_locally_cached(
            local_cache,
            uid=uid,
            level=level_comma_sep,
            jwt_insert_index=jwt_insert_index,
            serialized_without_jwt=serialized_without_jwt,
        )
        await push_to_local_caches(
            itgs,
            uid=uid,
            level=level_comma_sep,
            jwt_insert_index=jwt_insert_index,
            serialized_without_jwt=serialized_without_jwt,
        )
        return StreamingResponse(
            content=_inject_jwt(
                io.BytesIO(serialized_without_jwt), jwt_insert_index, jwt
            ),
            headers=HEADERS,
        )
    finally:
        await redis.delete(lock_key)


def get_locally_cached(
    cache: diskcache.Cache, *, uid: str, level: str, jwt: str
) -> Generator[Union[bool, bytes], None, None]:
    """Fetches the cached representation of the daily event with the given uid
    at the given level of access, modified to include the given JWT. This will
    yield nothing if the cached representation is not available.

    The first yield will be a boolean indicating whether the cached
    representation is available. If it is, the following yields will
    be the serialized response in parts.

    Args:
        cache (diskcache.Cache): The cache to use
        uid (str): The uid of the daily event
        level (str): The level of access, as a comma-separated string in ascending
            alphabetical order
        jwt (str): The JWT to include in the response

    Yields:
        bool: True if the cached representation is available, otherwise False
        *bytes: The serialized response in parts
    """
    result = cache.get(f"daily_events:external:{uid}:{level}", read=True)
    if result is None:
        yield False
        return

    yield True

    if isinstance(result, (bytes, bytearray, memoryview)):
        result = io.BytesIO(result)

    jwt_insert_index = int.from_bytes(result.read(4), "big", signed=False)
    yield from _inject_jwt(result, jwt_insert_index, jwt)


def _inject_jwt(
    serialized_without_jwt: io.BytesIO, jwt_insert_index: int, jwt: str
) -> Generator[bytes, None, None]:
    yield serialized_without_jwt.read(jwt_insert_index)
    yield jwt.encode("utf-8")
    yield serialized_without_jwt.read()


def set_locally_cached(
    cache: diskcache.Cache,
    *,
    uid: str,
    level: str,
    jwt_insert_index: int,
    serialized_without_jwt: Union[bytes, bytearray, memoryview],
    expires_in: int = 60 * 60 * 24 * 2,
) -> None:
    """Sets the locally cached representation of the daily event with the given
    uid at the given level of access.

    Args:
        cache (diskcache.Cache): The cache to use
        uid (str): The uid of the daily event
        level (str): The level of access, as a comma-separated string in ascending
            alphabetical order
        jwt_insert_index (int): The index at which the JWT can be inserted when
            reading the cached representation
        serialized_without_jwt (bytes): The serialized representation of the
            response, with the jwt as an empty string, such that the jwt_insert_index
            is the index of the closing quote of the empty string
        expires_in (int): The number of seconds after which the cache automatically
            expires this entry
    """
    serializable = bytearray(4 + len(serialized_without_jwt))
    serializable[:4] = jwt_insert_index.to_bytes(4, "big", signed=False)
    serializable[4:] = serialized_without_jwt

    cache.set(
        f"daily_events:external:{uid}:{level}",
        serializable,
        expire=expires_in,
        tag="collab",
    )


def evict_locally_cached(cache: diskcache.Cache, *, uid: str, level: str) -> None:
    """Evicts the locally cached representation of the daily event with the given
    uid at the given level of access.

    Args:

    """
    cache.delete(f"daily_events:external:{uid}:{level}")


async def evict_external_daily_event(itgs: Itgs, *, uid: str) -> None:
    """Evicts all cached representations of the daily event with the given uid,
    forcing them to be refilled at the next access. The cache will be collaboratively
    filled, meaning that the number of instances should not significantly affect
    the time it takes to fill the cache.

    This should be called if anything that would affect the external cached
    representation of the daily event changes.

    Args:
        itgs (Itgs): The integrations to (re)use
        uid (str): The uid of the daily event to evict
    """
    message = DailyEventsExternalPushCachePubSubMessage(
        uid=uid, min_checked_at=time.time(), level=None
    )

    message_bytes = message.json().encode("utf-8")

    pubsub_message = bytearray(4 + len(message_bytes))
    pubsub_message[:4] = len(message_bytes).to_bytes(4, "big", signed=False)
    pubsub_message[4:] = message_bytes

    redis = await itgs.redis()
    await redis.publish(b"ps:daily_events:external:push_cache", pubsub_message)


async def push_to_local_caches(
    itgs: Itgs,
    *,
    uid: str,
    level: str,
    jwt_insert_index: int,
    serialized_without_jwt: bytes,
) -> None:
    """Pushes the given serialized representation of the daily event with the given
    uid at the given level of access to all local caches. This should be called
    whenever the cached representation is fetched from the database, to avoid
    database load scaling with the number of backend instances, which makes
    tuning the number of backend instances difficult.

    Args:
        itgs (Itgs): The integrations to (re)use
        uid (str): The uid of the daily event
        level (str): The level of access, as a comma-separated string in ascending
            alphabetical order
        jwt_insert_index (int): The index at which the JWT can be inserted when
            reading the cached representation
        serialized_without_jwt (bytes): The serialized representation of the
            response, with the jwt as an empty string, such that the jwt_insert_index
            is the index of the closing quote of the empty string
    """
    message = DailyEventsExternalPushCachePubSubMessage(
        uid=uid, min_checked_at=time.time(), level=level
    )

    message_bytes = message.json().encode("utf-8")

    pubsub_message = bytearray(4 + len(message_bytes) + 8 + len(serialized_without_jwt))
    idx = 0
    pubsub_message[idx : idx + 4] = len(message_bytes).to_bytes(4, "big", signed=False)
    idx += 4
    pubsub_message[idx : idx + len(message_bytes)] = message_bytes
    idx += len(message_bytes)
    pubsub_message[idx : idx + 4] = jwt_insert_index.to_bytes(4, "big", signed=False)
    idx += 4
    pubsub_message[idx : idx + 4] = len(serialized_without_jwt).to_bytes(
        4, "big", signed=False
    )
    idx += 4
    pubsub_message[idx : idx + len(serialized_without_jwt)] = serialized_without_jwt
    idx += len(serialized_without_jwt)
    assert idx == len(pubsub_message)

    redis = await itgs.redis()
    await redis.publish(b"ps:daily_events:external:push_cache", pubsub_message)


async def cache_push_loop() -> NoReturn:
    """Loops forever, synchronizing the local cache with the database collaboratively.
    Anything which modifies one of the cached fields will publish a message to
    `ps:daily_events:external:push_cache` to notify instances to purge their local
    cache.

    Whenever we receive a messag
    """
    async with pps.PPSSubscription(
        pps.instance, "ps:daily_events:external:push_cache", "de_ext"
    ) as sub:
        async for raw_message in sub:
            message = io.BytesIO(raw_message)
            first_part_len = int.from_bytes(message.read(4), "big", signed=False)
            first_part = DailyEventsExternalPushCachePubSubMessage.parse_raw(
                message.read(first_part_len), content_type="application/json"
            )

            if first_part.level is not None:
                jwt_insert_index = int.from_bytes(message.read(4), "big", signed=False)
                serialized_without_jwt_len = int.from_bytes(
                    message.read(4), "big", signed=False
                )
                serialized_without_jwt = message.read(serialized_without_jwt_len)

            async with Itgs() as itgs:
                local_cache = await itgs.local_cache()
                if first_part.level is None:
                    for level in ALL_LEVELS:
                        evict_locally_cached(
                            local_cache, uid=first_part.uid, level=level
                        )
                else:
                    set_locally_cached(
                        local_cache,
                        uid=first_part.uid,
                        level=first_part.level,
                        jwt_insert_index=jwt_insert_index,
                        serialized_without_jwt=serialized_without_jwt,
                    )

                    listeners = cache_received_listeners.pop(
                        (first_part.uid, first_part.level), []
                    )
                    for listener in listeners:
                        listener(
                            first_part.uid,
                            first_part.level,
                            jwt_insert_index,
                            serialized_without_jwt,
                        )


class DailyEventsExternalPushCachePubSubMessage(BaseModel):
    uid: str = Field(
        description="The uid of the daily event which may have been modified"
    )
    min_checked_at: float = Field(
        description="Caches filled prior to this time should be evicted"
    )
    level: Optional[str] = Field(
        description="If specified, don't evict, instead, replace the cache at this level with the provided data"
    )


async def read_one_external_from_db(
    itgs: Itgs, *, uid: str, level: Set[DailyEventLevel]
) -> Optional[ExternalDailyEvent]:
    """Fetches the daily event with the given uid from the database, in the form
    we would return it to an external user with the given level of access. The JWT
    is left as a blank string.

    Args:
        itgs (Itgs): The integrations to (re)use
        uid (str): The uid of the daily event to fetch
        level (Set[DailyEventLevel]): The level of access

    Returns:
        ExternalDailyEvent, None: If the daily event exists, the external
            representation of it, otherwise None
    """
    conn = await itgs.conn()
    cursor = conn.cursor("strong")

    response = await cursor.execute(
        """
        SELECT
            journey_subcategories.external_name,
            journeys.title,
            instructors.name,
            journeys.description
        FROM journeys
        WHERE
            EXISTS (
                SELECT 1 FROM daily_events
                WHERE daily_events.uid = ?
                  AND EXISTS (
                    SELECT 1 FROM daily_event_journeys
                    WHERE daily_event_journeys.daily_event_id = daily_events.id
                      AND daily_event_journeys.journey_id = journeys.id
                  )
            )
            AND journeys.deleted_at IS NULL
        """,
        (uid,),
    )

    if not response.results:
        return None

    return ExternalDailyEvent(
        uid=uid,
        jwt="",
        journeys=[
            ExternalDailyEventJourney(
                category=ExternalDailyEventJourneyCategory(external_name=row[0]),
                title=row[1],
                instructor=ExternalDailyEventJourneyInstructor(name=row[2]),
                description=ExternalDailyEventJourneyDescription(text=row[3]),
                access=ExternalDailyEventJourneyAccess(
                    start="start_full" in level,
                ),
            )
            for row in response.results
        ],
        access=ExternalDailyEventAccess(
            start_random=len(level.intersection({"start_full", "start_random"})) > 0,
        ),
    )
