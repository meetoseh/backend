import json
from image_files.models import ImageFileRef
from itgs import Itgs
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from typing import (
    AsyncIterator,
    Callable,
    Dict,
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
import image_files.auth
import perpetual_pub_sub as pps
import diskcache
import asyncio
import random
import time
import io


ALL_LEVELS: List[str] = ("read,start_full", "read,start_random", "read,start_none")
"""All the levels we actually use, so that we can evict all the caches when
necessary
"""

cache_received_listeners: Dict[
    Tuple[str, str], List[Callable[[str, str, bytes], None]]
] = dict()
"""A mapping from (daily_event_uid, level) to a list of listeners to call when
the cached representation of the daily event with the given uid is received.

Each callable is passed (uid, level, raw) and will have already been removed
from the list of listeners before being called, meaning if it wants to be called
again it must re-register itself.

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

    local_cache = await itgs.local_cache()
    result_gen = get_locally_cached(itgs, uid=uid, level=level_comma_sep)
    have_local_cache = await result_gen.__anext__()
    if have_local_cache:
        return StreamingResponse(
            content=result_gen,
            headers=HEADERS,
        )

    # we haven't yielded control of the main thread since we checked the local
    # cache here, so we're still safe to register a listener for the cache
    # without racing. however we can't wait until we check if we've got the
    # lock, since we'd have a race condition

    raw: Optional[bytes] = None
    cache_received_event: asyncio.Event = asyncio.Event()

    def on_cache_recieved(_: str, __: str, new_raw: bytes):
        nonlocal raw
        raw = new_raw
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
            assert isinstance(raw, (bytes, bytearray, memoryview))
            result_gen = _inject_jwts(itgs, raw=io.BytesIO(raw), uid=uid, level=level)
            return StreamingResponse(content=result_gen, headers=HEADERS)
        except asyncio.TimeoutError:
            slack = await itgs.slack()
            await slack.send_web_error_message(
                "daily_events.lib.read_one_external: Timeout waiting for cache_received_event"
            )

            # fall down to as if we took the lock

    try:
        event_without_jwts = await read_one_external_from_db(itgs, uid=uid, level=level)
        if event_without_jwts is None:
            return None

        raw = convert_external_daily_event_to_cache_format(event_without_jwts)
        set_locally_cached(local_cache, uid=uid, level=level_comma_sep, raw=raw)
        await push_to_local_caches(itgs, uid=uid, level=level_comma_sep, raw=raw)
        return StreamingResponse(
            content=_inject_jwts(itgs, raw=io.BytesIO(raw), uid=uid, level=level),
            headers=HEADERS,
        )
    finally:
        await redis.delete(lock_key)


async def get_locally_cached(
    itgs: Itgs, *, uid: str, level: str
) -> AsyncIterator[Union[bool, bytes]]:
    """Fetches the cached representation of the daily event with the given uid
    at the given level of access, generating jwts and inserting them as necessary.

    The first yield will be a boolean indicating whether the cached
    representation is available. If it is, the following yields will
    be the serialized response in parts.

    Args:
        itgs (Itgs): The integrations to (re)use
        uid (str): The uid of the daily event
        level (str): The level of access, as a comma-separated string in ascending
            alphabetical order

    Yields:
        bool: True if the cached representation is available, otherwise False
        *bytes: The serialized response in parts
    """
    cache = await itgs.local_cache()
    result = cache.get(
        f"daily_events:external:{uid}:{level}".encode("utf-8"), read=True
    )
    if result is None:
        yield False
        return

    yield True

    if isinstance(result, (bytes, bytearray, memoryview)):
        result = io.BytesIO(result)

    async for part in _inject_jwts(itgs, raw=result, uid=uid, level=level):
        yield part


async def _inject_jwts(
    itgs: Itgs, *, raw: io.BytesIO, uid: str, level: Union[Set[DailyEventLevel], str]
) -> AsyncIterator[bytes]:
    if isinstance(level, str):
        level: Set[DailyEventLevel] = set(level.split(","))

    daily_event_jwt = await daily_events.auth.create_jwt(
        itgs, daily_event_uid=uid, level=level
    )
    while True:
        length = raw.read(4)
        if not length:
            return

        length = int.from_bytes(length, "big", signed=False)
        type_marker = raw.read(1)
        value = raw.read(length)

        if type_marker == b"\x01":
            yield value
        elif type_marker == b"\x02":
            yield daily_event_jwt.encode("ascii")
        elif type_marker == b"\x03":
            image_file_uid = value.decode("ascii")
            assert image_file_uid[:8] == "oseh_if_"
            image_file_jwt = await image_files.auth.create_jwt(
                itgs, image_file_uid=image_file_uid
            )
            yield image_file_jwt.encode("ascii")


def set_locally_cached(
    cache: diskcache.Cache,
    *,
    uid: str,
    level: str,
    raw: bytes,
    expires_in: int = 60 * 60 * 24 * 2,
) -> None:
    """Sets the locally cached representation of the daily event with the given
    uid at the given level of access.

    Args:
        cache (diskcache.Cache): The cache to use
        uid (str): The uid of the daily event
        level (str): The level of access, as a comma-separated string in ascending
            alphabetical order
        raw (bytes): The raw bytes of the cached representation, already formatted
            appropriately. To convert an ExternalDailyEvent to this format, use
            convert_external_daily_event_to_cache_format.
        expires_in (int): The number of seconds after which the cache automatically
            expires this entry
    """
    cache.set(
        f"daily_events:external:{uid}:{level}".encode("utf-8"),
        raw,
        expire=expires_in,
        tag="collab",
    )


def convert_external_daily_event_to_cache_format(event: ExternalDailyEvent) -> bytes:
    """Converts an ExternalDailyEvent to the cache format. See
    the description for the key in our diskcache docs for more
    information about this format.

    Args:
        event (ExternalDailyEvent): The event to convert

    Returns:
        bytes: The cache format
    """
    # serializing ourself here is less error-prone for getting the marks correct
    # and is very fast

    result = io.BytesIO()
    insert_length_at = result.tell()

    def inject_length_and_mark():
        nonlocal insert_length_at

        curr_pos = result.tell()
        true_length = curr_pos - insert_length_at - 5
        result.seek(insert_length_at)
        result.write(true_length.to_bytes(4, "big", signed=False))

        result.seek(curr_pos)
        insert_length_at = curr_pos

    result.write(b'\x00\x00\x00\x00\x01{"uid":"')
    result.write(event.uid.encode("ascii"))  # won't contain any special characters
    result.write(b'","access":{"start_random":')
    if event.access.start_random:
        result.write(b"true")
    else:
        result.write(b"false")
    result.write(b'},"jwt":"')
    inject_length_and_mark()
    insert_length_at += 5  # skip over first marker
    result.write(b'\x00\x00\x00\x00\x02\x00\x00\x00\x00\x01","journeys":[')
    for idx, journey in enumerate(event.journeys):
        if idx != 0:
            result.write(b",")
        result.write(b'{"uid":"')
        result.write(journey.uid.encode("ascii"))
        result.write(b'","category":{"external_name":')
        result.write(json.dumps(journey.category.external_name).encode("utf-8"))
        result.write(b'},"title":')
        result.write(json.dumps(journey.title).encode("utf-8"))
        result.write(b',"instructor":{"name":')
        result.write(json.dumps(journey.instructor.name).encode("utf-8"))
        result.write(b'},"description":{"text":')
        result.write(json.dumps(journey.description.text).encode("utf-8"))
        result.write(b'},"background_image":{"uid":"')
        result.write(journey.background_image.uid.encode("ascii"))
        result.write(b'","jwt":"')
        inject_length_and_mark()
        result.write(b"\x00\x00\x00\x00\x03")
        result.write(journey.background_image.uid.encode("ascii"))
        inject_length_and_mark()
        result.write(b'\x00\x00\x00\x00\x01"},"access":{"start":')
        if journey.access.start:
            result.write(b"true")
        else:
            result.write(b"false")
        result.write(b"}}")

    result.write(b"]}")
    inject_length_and_mark()

    return result.getvalue()


def evict_locally_cached(cache: diskcache.Cache, *, uid: str, level: str) -> None:
    """Evicts the locally cached representation of the daily event with the given
    uid at the given level of access.

    Args:

    """
    cache.delete(f"daily_events:external:{uid}:{level}".encode("utf-8"))


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

    pubsub_message = len(message_bytes).to_bytes(4, "big", signed=False) + message_bytes

    redis = await itgs.redis()
    await redis.publish(b"ps:daily_events:external:push_cache", pubsub_message)


async def push_to_local_caches(itgs: Itgs, *, uid: str, level: str, raw: bytes) -> None:
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
        raw (bytes): The serialized representation of the daily event
    """
    message = DailyEventsExternalPushCachePubSubMessage(
        uid=uid, min_checked_at=time.time(), level=level
    )

    message_bytes = message.json().encode("utf-8")
    pubsub_message = (
        len(message_bytes).to_bytes(4, "big", signed=False) + message_bytes + raw
    )

    redis = await itgs.redis()
    await redis.publish(b"ps:daily_events:external:push_cache", pubsub_message)


async def cache_push_loop() -> NoReturn:
    """Loops forever, synchronizing the local cache with the database collaboratively.
    Anything which modifies one of the cached fields will publish a message to
    `ps:daily_events:external:push_cache` to notify instances to purge their local
    cache.
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
                raw = message.read()

            async with Itgs() as itgs:
                local_cache = await itgs.local_cache()
                if first_part.level is None:
                    for level in ALL_LEVELS:
                        evict_locally_cached(
                            local_cache, uid=first_part.uid, level=level
                        )
                else:
                    set_locally_cached(
                        local_cache, uid=first_part.uid, level=first_part.level, raw=raw
                    )

                    listeners = cache_received_listeners.pop(
                        (first_part.uid, first_part.level), []
                    )
                    for listener in listeners:
                        listener(first_part.uid, first_part.level, raw)


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
    we would return it to an external user with the given level of access. The JWTs
    are left as blank strings.

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
            journeys.description,
            image_files.uid,
            journeys.uid
        FROM journeys
        JOIN journey_subcategories ON journey_subcategories.id = journeys.journey_subcategory_id
        JOIN image_files ON image_files.id = journeys.background_image_file_id
        JOIN instructors ON instructors.id = journeys.instructor_id
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
                background_image=ImageFileRef(uid=row[4], jwt=""),
                access=ExternalDailyEventJourneyAccess(
                    start="start_full" in level,
                ),
                uid=row[5],
            )
            for row in response.results
        ],
        access=ExternalDailyEventAccess(
            start_random=len(level.intersection({"start_full", "start_random"})) > 0,
        ),
    )
