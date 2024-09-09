"""This manages the client flow cache to reduce hits on the database and the amount of
time spent parsing schemas.
"""

import asyncio
from dataclasses import dataclass
import io
import json
from openapi_schema_validator import OAS30Validator
from typing import Dict, List, Optional, Set, cast
import jsonschema.protocols

from client_flows.lib.parse_flow_screens import decode_flow_screens, encode_flow_screens
from error_middleware import handle_error
from itgs import Itgs
from lib.client_flows.client_flow_rule import ClientFlowRules, client_flow_rules_adapter
from lib.client_flows.client_flow_screen import ClientFlowScreen
from lib.client_flows.flow_flags import ClientFlowFlag
from lifespan import lifespan_handler
import perpetual_pub_sub as pps


@dataclass
class ClientFlow:
    """Describes the in-memory representation of a client flow from the flow cache. We
    omit columns that aren't required for triggering client flows, e.g., the name and
    description.
    """

    uid: str
    """The stable unique identifier for this flow"""

    slug: str
    """The slug for this client flow"""

    client_schema: jsonschema.protocols.Validator
    """The schema for the client parameters of the flow, already parsed and ready to use."""

    client_schema_raw: dict
    """The raw client schema object"""

    server_schema: jsonschema.protocols.Validator
    """The schema for the server parameters of the flow, already parsed and ready to use."""

    server_schema_raw: dict
    """The raw server schema object"""

    replaces: bool
    """True if, when triggering this flow, the users screens should be cleared before
    adding our screens. False if our screens should be inserted at the front of the
    queue without clearing the existing items.
    """

    screens: List[ClientFlowScreen]
    """The screens to insert into the queue when triggering this flow"""

    flags: ClientFlowFlag
    """The boolean configuration options generally loosely related to access control
    for this client flow
    """

    rules: ClientFlowRules
    """The rules that should be checked at trigger time for this client flow"""


valid_client_flows: Optional[Set[str]] = None
memory_cache_size = 200

# only minimal flows cached like this
old_cache: Dict[str, ClientFlow] = {}
latest_cache: Dict[str, ClientFlow] = {}


async def get_client_flow(
    itgs: Itgs, /, *, slug: str, minimal: bool = True
) -> Optional[ClientFlow]:
    """Fetches the client flow with the given slug from the nearest cache,
    filling any caches that were missed along the way.

    Args:
        itgs (Itgs): the integrations to (re)use
        slug (str): the slug of the client flow to fetch

    Returns:
        ClientFlow, None: if there exists a client flow with the given slug, the
            in-memory representation, otherwise None.
    """
    if minimal:
        in_memory = read_client_flow_from_in_memory(slug)
        if in_memory is not None:
            return in_memory

    on_disk = await read_client_flow_from_disk(itgs, slug=slug, minimal=minimal)
    if on_disk is not None:
        parsed = convert_from_raw(on_disk)
        write_client_flow_to_in_memory(parsed)
        return parsed

    valid = await get_valid_client_flow_slugs(itgs)
    if slug not in valid:
        return None

    in_db = await read_full_client_flow_from_db(itgs, slug=slug)
    if in_db is None:
        await purge_valid_client_flows_cache(itgs)
        return None

    if not minimal:
        full_raw = convert_to_raw(in_db)
        await write_client_flow_to_disk(itgs, slug=slug, minimal=False, raw=full_raw)
        return in_db

    edit_flow_to_minimal_info(in_db)
    write_client_flow_to_in_memory(in_db)
    raw = convert_to_raw(in_db)
    await write_client_flow_to_disk(itgs, slug=slug, raw=raw, minimal=True)
    return in_db


async def get_valid_client_flow_slugs(itgs: Itgs, /) -> Set[str]:
    """Returns the client flow slugs that are valid to trigger. This is cached in
    memory on this instance, busted on any change to any client flow, but not carefully
    protected to races (since client flows are created/renamed/deleted fairly rarely,
    and almost always edited after)
    """
    global valid_client_flows
    if valid_client_flows is not None:
        return valid_client_flows

    db_batch_size = 100
    last_flow_slug: Optional[str] = None
    result = set()

    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    while True:
        response = await cursor.execute(
            "SELECT slug FROM client_flows WHERE (? IS NULL OR slug > ?) ORDER BY slug ASC LIMIT ?",
            (last_flow_slug, last_flow_slug, db_batch_size),
        )
        if not response.results:
            break

        for row in response.results:
            result.add(row[0])

        last_flow_slug = response.results[-1][0]

        if len(response.results) < db_batch_size:
            break

    valid_client_flows = result
    return result


async def purge_client_flow_cache(itgs: Itgs, /, *, slug: str) -> None:
    """Purges any cached client flows with the given slug, everywhere.
    Typically, if you are doing this, you also want to call
    lib.client_flows.analysis#evict to clear the analysis cache,
    and you may want to call #purge_valid_client_flows_cache
    """
    await publish_client_flow_delete(itgs, slug=slug)


async def purge_valid_client_flows_cache(itgs: Itgs) -> None:
    """Purges the cache of valid client flow slugs everywhere"""
    await publish_valid_client_flows_changed(itgs)


def read_client_flow_from_in_memory(slug: str) -> Optional[ClientFlow]:
    """Reads the client flow with the given slug from the in-memory cache,
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


def write_client_flow_to_in_memory(client_flow: ClientFlow) -> None:
    """Writes the client flow to the in-memory cache, promoting it to the latest
    if it was in the old cache. This will evict the old cache if there are too
    many items in the cache after the write.

    O(1)
    """
    global old_cache, latest_cache

    old_cache.pop(client_flow.slug, None)
    latest_cache[client_flow.slug] = client_flow

    if len(old_cache) + len(latest_cache) > memory_cache_size:
        old_cache = latest_cache
        latest_cache = dict()


def delete_client_flow_from_in_memory(slug: str) -> None:
    """Deletes the client flow with the given slug from the in-memory cache"""
    latest_cache.pop(slug, None)
    old_cache.pop(slug, None)


def convert_to_raw(client_flow: ClientFlow) -> bytes:
    """Converts the given client flow to the raw bytes that we store on disk / send over
    the redis pipe
    """
    return json.dumps(
        {
            "uid": client_flow.uid,
            "slug": client_flow.slug,
            "client_schema": client_flow.client_schema_raw,
            "server_schema": client_flow.server_schema_raw,
            "replaces": client_flow.replaces,
            "screens": encode_flow_screens(client_flow.screens),
            "flags": int(client_flow.flags),
            "rules": client_flow_rules_adapter.dump_python(
                client_flow.rules, exclude_none=True
            ),
        }
    ).encode("utf-8")


def convert_from_raw(raw: bytes) -> ClientFlow:
    """Converts the raw bytes to a client flow object"""
    as_python = cast(dict, json.loads(raw))

    return ClientFlow(
        uid=as_python["uid"],
        slug=as_python["slug"],
        client_schema=cast(
            jsonschema.protocols.Validator, OAS30Validator(as_python["client_schema"])
        ),
        client_schema_raw=as_python["client_schema"],
        server_schema=cast(
            jsonschema.protocols.Validator, OAS30Validator(as_python["server_schema"])
        ),
        server_schema_raw=as_python["server_schema"],
        replaces=as_python["replaces"],
        screens=decode_flow_screens(as_python["screens"]),
        flags=ClientFlowFlag(as_python["flags"]),
        rules=client_flow_rules_adapter.validate_python(as_python.get("rules", [])),
    )


async def read_client_flow_from_disk(
    itgs: Itgs, /, *, slug: str, minimal: bool
) -> Optional[bytes]:
    """Reads the raw client flow with the given slug from the disk cache, if it
    is there
    """
    cache = await itgs.local_cache()
    suffix = ":full" if not minimal else ""
    return cast(
        Optional[bytes], cache.get(f"client_flows:{slug}{suffix}".encode("utf-8"))
    )


async def write_client_flow_to_disk(
    itgs: Itgs, /, *, slug: str, minimal: bool, raw: bytes
) -> None:
    """Writes the raw client flow associated with the given slug to the disk cache"""
    cache = await itgs.local_cache()
    suffix = ":full" if not minimal else ""
    cache.set(f"client_flows:{slug}{suffix}".encode("utf-8"), raw, tag="collab")


async def delete_client_flow_from_disk(
    itgs: Itgs, /, *, slug: str, minimal: bool
) -> None:
    """Deletes the raw client flow associated with the given slug from the disk cache"""
    cache = await itgs.local_cache()
    suffix = ":full" if not minimal else ""
    cache.delete(f"client_flows:{slug}{suffix}".encode("utf-8"))


async def publish_client_flow_delete(itgs: Itgs, /, *, slug: str) -> None:
    """Publishes a message via redis that tells everyone to delete the client flow with
    the given slug from all caches
    """
    encoded_slug = slug.encode("utf-8")
    redis = await itgs.redis()
    type_ = 0
    await redis.publish(
        b"ps:client_flows",
        type_.to_bytes(1, "big", signed=False)
        + len(encoded_slug).to_bytes(4, "big", signed=False)
        + encoded_slug,
    )


async def publish_valid_client_flows_changed(itgs: Itgs, /) -> None:
    """Publishes a message via redis that tells everyone to delete the valid client flow
    slugs cache
    """
    redis = await itgs.redis()
    type_ = 1
    await redis.publish(
        b"ps:client_flows",
        type_.to_bytes(1, "big", signed=False),
    )


async def handle_received_client_flow_delete(itgs: Itgs, /, *, slug: str) -> None:
    """Handles a received message that tells us to delete the client flow with the given
    slug from all caches
    """
    delete_client_flow_from_in_memory(slug)
    await delete_client_flow_from_disk(itgs, slug=slug, minimal=True)
    await delete_client_flow_from_disk(itgs, slug=slug, minimal=False)


async def handle_received_valid_client_flows_changed(itgs: Itgs, /) -> None:
    """Handles a received message that tells us to delete the valid client flow slugs
    cache
    """
    global valid_client_flows
    valid_client_flows = None


async def _subscribe_client_flow_deletes() -> None:
    assert pps.instance is not None
    try:
        async with pps.PPSSubscription(
            pps.instance,
            "ps:client_flows",
            f"subscribe_client_flow_deletes",
        ) as sub:
            async for message in sub:
                msg = io.BytesIO(message)
                msg_type = int.from_bytes(msg.read(1), "big", signed=False)

                if msg_type == 0:
                    slug_len = int.from_bytes(msg.read(4), "big", signed=False)
                    slug = msg.read(slug_len).decode("utf-8")

                    async with Itgs() as itgs:
                        await handle_received_client_flow_delete(itgs, slug=slug)
                elif msg_type == 1:
                    async with Itgs() as itgs:
                        await handle_received_valid_client_flows_changed(itgs)
    except Exception as e:
        if pps.instance.exit_event.is_set() and isinstance(e, pps.PPSShutdownException):
            return
        await handle_error(e)
    finally:
        print(f"lib.client_flows.flow_cache#_subscribe_client_flow_deletes exiting")


@lifespan_handler
async def _do_subscribe_client_flow_deletes():
    task = asyncio.create_task(_subscribe_client_flow_deletes())
    yield


async def read_full_client_flow_from_db(
    itgs: Itgs, /, *, slug: str
) -> Optional[ClientFlow]:
    """Fetches the client flow with the given slug from the database, if it
    exists, otherwise returns None.
    """
    conn = await itgs.conn()
    cursor = conn.cursor("weak")
    response = await cursor.execute(
        """
SELECT
    uid,
    slug,
    client_schema,
    server_schema,
    replaces,
    screens,
    flags,
    rules
FROM client_flows
WHERE slug = ?
        """,
        (slug,),
    )
    if not response.results:
        return None

    row = response.results[0]
    client_schema_raw = json.loads(row[2])
    server_schema_raw = json.loads(row[3])
    screens = decode_flow_screens(row[5])
    rules = client_flow_rules_adapter.validate_python(json.loads(row[7]))

    client_schema = cast(
        jsonschema.protocols.Validator, OAS30Validator(client_schema_raw)
    )
    server_schema = cast(
        jsonschema.protocols.Validator, OAS30Validator(server_schema_raw)
    )

    return ClientFlow(
        uid=row[0],
        slug=row[1],
        client_schema=client_schema,
        client_schema_raw=client_schema_raw,
        server_schema=server_schema,
        server_schema_raw=server_schema_raw,
        replaces=bool(row[4]),
        screens=screens,
        flags=ClientFlowFlag(row[6]),
        rules=rules,
    )


def edit_flow_to_minimal_info(client_flow: ClientFlow) -> None:
    """Strips information from the given client flow that is not required for
    triggering it, to try to reduce space
    """
    for screen in client_flow.screens:
        screen.name = None
