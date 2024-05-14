"""This manages the client screen cache to reduce hits on the database and the amount of
time spent parsing schemas.
"""

import asyncio
from dataclasses import dataclass
import io
import json
from typing import Dict, Optional, cast
import jsonschema.protocols
from openapi_schema_validator import OAS30Validator

from error_middleware import handle_error
from itgs import Itgs
from lib.client_flows.screen_flags import ClientScreenFlag
from lib.client_flows.screen_schema import ScreenSchemaRealizer
from lifespan import lifespan_handler
import perpetual_pub_sub as pps


@dataclass
class ClientScreen:
    """The in-memory representation of a client screen from the client screen cache. We
    omit columns that are not required for realizing client screens
    """

    uid: str
    """The primary stable external row identifier"""

    slug: str
    """The slug of the screen as hard-coded into the clients"""

    raw_schema: dict
    """The raw OpenAPI 3.0.3 schema object for the screen"""

    schema: jsonschema.protocols.Validator
    """The schema which the realizer follows in order to realize the screen input
    parameters into the format used by the client. The screen realizer's `is_safe`
    function should be preferred for determining what input parameters require trusted
    input.
    """

    realizer: ScreenSchemaRealizer
    """The realizer for this screen, i.e., the consumer of the schema that produces an
    object which is passed to the client. This consumer is completely specified by the
    schema object.
    """

    flags: ClientScreenFlag
    """The boolean's associated with this screen, which are generally (loosely) related
    to access controls
    """


memory_cache_size = 200
old_cache: Dict[str, ClientScreen] = {}
latest_cache: Dict[str, ClientScreen] = {}


async def get_client_screen(itgs: Itgs, /, *, slug: str) -> Optional[ClientScreen]:
    """Fetches the client screen with the given slug from the nearest cache,
    filling any caches that were missed along the way.

    Args:
        itgs (Itgs): the integrations to (re)use
        slug (str): the slug of the client screen to fetch

    Returns:
        ClientScreen, None: if there exists a client screen with the given slug, the
            in-memory representation, otherwise None.
    """
    in_memory = read_client_screen_from_in_memory(slug)
    if in_memory is not None:
        return in_memory

    on_disk = await read_client_screen_from_disk(itgs, slug=slug)
    if on_disk is not None:
        parsed = convert_from_raw(on_disk)
        write_client_screen_to_in_memory(parsed)
        return parsed

    in_db = await read_client_screen_from_db(itgs, slug=slug)
    if in_db is None:
        return None

    write_client_screen_to_in_memory(in_db)
    raw = convert_to_raw(in_db)
    await write_client_screen_to_disk(itgs, slug=slug, raw=raw)
    return in_db


async def purge_client_screen_cache(itgs: Itgs, /, *, slug: str) -> None:
    """Purges any cached client screens with the given slug, everywhere"""
    await publish_client_screen_delete(itgs, slug=slug)


def read_client_screen_from_in_memory(slug: str) -> Optional[ClientScreen]:
    """Reads the client screen with the given slug from the in-memory cache,
    promoting it to the latest cache if found in the old cache.

    O(1)
    """
    res = latest_cache.get(slug)
    if res is not None:
        return res

    res = old_cache.pop(slug, None)
    if res is not None:
        latest_cache[slug] = res
    return res


def write_client_screen_to_in_memory(client_screen: ClientScreen) -> None:
    """Writes the client screen to the in-memory cache, promoting it to the latest
    if it was in the old cache. This will evict the old cache if there are too
    many items in the cache after the write.

    O(1)
    """
    global old_cache, latest_cache

    old_cache.pop(client_screen.slug, None)
    latest_cache[client_screen.slug] = client_screen

    if len(old_cache) + len(latest_cache) > memory_cache_size:
        old_cache = latest_cache
        latest_cache = dict()


def delete_client_screen_from_in_memory(slug: str) -> None:
    """Deletes the client screen with the given slug from the in-memory cache"""
    latest_cache.pop(slug, None)
    old_cache.pop(slug, None)


def convert_to_raw(client_screen: ClientScreen) -> bytes:
    """Converts the given client screen to the raw bytes that we store on disk / send over
    the redis pipe
    """
    return json.dumps(
        {
            "uid": client_screen.uid,
            "slug": client_screen.slug,
            "schema": client_screen.raw_schema,
            "flags": int(client_screen.flags),
        }
    ).encode("utf-8")


def convert_from_raw(raw: bytes) -> ClientScreen:
    """Converts the raw bytes to a client screen object"""
    as_python = json.loads(raw)

    raw_schema = as_python["schema"]
    return ClientScreen(
        uid=as_python["uid"],
        slug=as_python["slug"],
        raw_schema=raw_schema,
        schema=cast(
            jsonschema.protocols.Validator, OAS30Validator(as_python["schema"])
        ),
        realizer=ScreenSchemaRealizer(raw_schema),
        flags=ClientScreenFlag(as_python["flags"]),
    )


async def read_client_screen_from_disk(itgs: Itgs, /, *, slug: str) -> Optional[bytes]:
    """Reads the raw client screen with the given slug from the disk cache, if it
    is there
    """
    cache = await itgs.local_cache()
    return cast(Optional[bytes], cache.get(f"client_screens:{slug}".encode("utf-8")))


async def write_client_screen_to_disk(itgs: Itgs, /, *, slug: str, raw: bytes) -> None:
    """Writes the raw client screen associated with the given slug to the disk cache"""
    cache = await itgs.local_cache()
    cache.set(f"client_screens:{slug}".encode("utf-8"), raw, tag="collab")


async def delete_client_screen_from_disk(itgs: Itgs, /, *, slug: str) -> None:
    """Deletes the raw client screen associated with the given slug from the disk cache"""
    cache = await itgs.local_cache()
    cache.delete(f"client_screens:{slug}".encode("utf-8"))


async def publish_client_screen_delete(itgs: Itgs, /, *, slug: str) -> None:
    """Publishes a message via redis that tells everyone to delete the client screen with
    the given slug from all caches
    """
    encoded_slug = slug.encode("utf-8")
    redis = await itgs.redis()
    await redis.publish(
        b"ps:client_screens",
        len(encoded_slug).to_bytes(4, "big", signed=False) + encoded_slug,
    )


async def handle_received_client_screen_delete(itgs: Itgs, /, *, slug: str) -> None:
    """Handles a received message that tells us to delete the client screen with the given
    slug from all caches
    """
    delete_client_screen_from_in_memory(slug)
    await delete_client_screen_from_disk(itgs, slug=slug)


async def _subscribe_client_screen_deletes() -> None:
    assert pps.instance is not None
    try:
        async with pps.PPSSubscription(
            pps.instance,
            "ps:client_screens",
            f"subscribe_client_screen_deletes",
        ) as sub:
            async for message in sub:
                msg = io.BytesIO(message)
                slug_len = int.from_bytes(msg.read(4), "big", signed=False)
                slug = msg.read(slug_len).decode("utf-8")

                async with Itgs() as itgs:
                    await handle_received_client_screen_delete(itgs, slug=slug)
    except Exception as e:
        if pps.instance.exit_event.is_set() and isinstance(e, pps.PPSShutdownException):
            return
        await handle_error(e)
    finally:
        print(f"lib.client_flows.screen_cache#_subscribe_client_screen_deletes exiting")


@lifespan_handler
async def _do_subscribe_client_screen_deletes():
    task = asyncio.create_task(_subscribe_client_screen_deletes())
    yield


async def read_client_screen_from_db(
    itgs: Itgs, /, *, slug: str
) -> Optional[ClientScreen]:
    """Fetches the client screen with the given slug from the database, if it
    exists, otherwise returns None.
    """
    conn = await itgs.conn()
    cursor = conn.cursor("weak")
    response = await cursor.execute(
        """
SELECT
    uid,
    slug,
    schema,
    flags
FROM client_screens
WHERE slug = ?
        """,
        (slug,),
    )
    if not response.results:
        return None

    row = response.results[0]
    raw_schema = json.loads(row[2])
    return ClientScreen(
        uid=row[0],
        slug=row[1],
        raw_schema=raw_schema,
        schema=cast(jsonschema.protocols.Validator, OAS30Validator(raw_schema)),
        realizer=ScreenSchemaRealizer(raw_schema),
        flags=ClientScreenFlag(row[3]),
    )
