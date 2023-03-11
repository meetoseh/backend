"""This library is intended to facilitate fetching information about an interactive
prompt using a 2-layer cooperative caching strategy (db -> local disk)
"""
import asyncio
import json
import random
from typing import AsyncIterator, Dict, List, Literal, NoReturn, Optional, Union
from fastapi.responses import Response, StreamingResponse
from error_middleware import handle_contextless_error, handle_error
from itgs import Itgs
from dataclasses import dataclass
import perpetual_pub_sub as pps
import io


@dataclass
class _InteractivePromptFromDB:
    uid: str
    prompt: str
    duration_seconds: int
    journey_subcategory: Optional[str]


HEADERS = {
    "Content-Type": "application/json; charset=utf-8",
}


async def read_one_external(
    itgs: Itgs,
    *,
    interactive_prompt_uid: str,
    interactive_prompt_jwt: str,
    interactive_prompt_session_uid: str,
) -> Optional[Response]:
    """Returns information on the given interactive prompt from the most suitable
    source, injecting the given user-specific information in an efficient manner
    (i.e., avoiding expensive serialization/deserialization). Note that this
    returns an ExternalInteractivePrompt already serialized appropriately for a
    response - this is because often the fully serialized form can be achieved
    without any parsing. Furthermore, the response may be a streaming response
    if we can form the response without even ever loading it all into memory.

    Care is taken with this endpoint to greatly reduce the odds of catastrophic
    cache misses (i.e., where so many instances attempt to fill a cache that is
    protecting the db that none of them succeed, so the db isn't protected,
    causing more to fail, etc)

    Args:
        itgs (Itgs): The integrations to (re)use
        interactive_prompt_uid (str): The UID of the interactive prompt to fetch
        interactive_prompt_jwt (str): The JWT which will be injected into the
            returned interactive prompt so that the recipient can interact with it
        interactive_prompt_session_uid (str): The session UID which will be
            injected into the returned interactive prompt so that the recipient
            can interact with it

    Returns:
        (Response or None): The interactive prompt, or None if it is not available
            anywhere because there is no interactive prompt with that uid.
    """
    local_stored_format = await read_local_cache(
        itgs, interactive_prompt_uid=interactive_prompt_uid
    )
    if local_stored_format is not None:
        if isinstance(local_stored_format, bytes):
            local_stored_format = io.BytesIO(local_stored_format)
        return StreamingResponse(
            content=convert_stored_format_to_response(
                itgs,
                interactive_prompt_jwt=interactive_prompt_jwt,
                interactive_prompt_session_uid=interactive_prompt_session_uid,
                stored_format=local_stored_format,
            ),
            headers=HEADERS,
            status_code=200,
        )

    redis = await itgs.redis()
    got_data_event = asyncio.Event()
    events = waiting_for_cache.get(interactive_prompt_uid)
    if events is None:
        events = []
        waiting_for_cache[interactive_prompt_uid] = events

    events.append(got_data_event)

    lock_key = (
        f"interactive_prompts:external:cache_lock:{interactive_prompt_uid}".encode(
            "ascii"
        )
    )
    got_lock = await redis.set(lock_key, "1", nx=True, ex=3)
    if not got_lock:
        wait_future = asyncio.create_task(got_data_event.wait())
        try:
            await asyncio.wait_for(wait_future, timeout=3)
        except asyncio.TimeoutError as e:
            await handle_error(
                e,
                extra_info="waiting for interactive prompt cache lock timed out; treating as if we got the lock",
            )

        if wait_future.done() and not wait_future.cancelled():
            local_stored_format = await read_local_cache(
                itgs, interactive_prompt_uid=interactive_prompt_uid
            )
            if local_stored_format is None:
                await handle_contextless_error(
                    extra_info="got data event, but still nothing in local cache for interactive prompt"
                )
                # fall down into the got-lock scenario
            else:
                if isinstance(local_stored_format, bytes):
                    local_stored_format = io.BytesIO(local_stored_format)
                return StreamingResponse(
                    content=convert_stored_format_to_response(
                        itgs,
                        interactive_prompt_jwt=interactive_prompt_jwt,
                        interactive_prompt_session_uid=interactive_prompt_session_uid,
                        stored_format=local_stored_format,
                    ),
                    headers=HEADERS,
                )
        else:
            wait_future.cancel()
            events.remove(got_data_event)
            if not events and waiting_for_cache.get(interactive_prompt_uid) is events:
                del waiting_for_cache[interactive_prompt_uid]

    # got the lock, or we timed out waiting for it to be filled
    try:
        db_value = await get_interactive_prompt_from_db(
            itgs, interactive_prompt_uid=interactive_prompt_uid
        )

        if db_value is None:
            return None

        stored_format_stream = io.BytesIO()
        convert_interactive_prompt_to_stored_format(db_value, stored_format_stream)
        stored_format = stored_format_stream.getvalue()
        await write_local_cache(
            itgs,
            interactive_prompt_uid=interactive_prompt_uid,
            stored_format=stored_format,
        )
        await push_interactive_prompt_to_caches(
            itgs,
            interactive_prompt_uid=interactive_prompt_uid,
            stored_format=stored_format,
        )
        return StreamingResponse(
            content=convert_stored_format_to_response(
                itgs,
                interactive_prompt_jwt=interactive_prompt_jwt,
                interactive_prompt_session_uid=interactive_prompt_session_uid,
                stored_format=io.BytesIO(stored_format),
            ),
            headers=HEADERS,
        )
    finally:
        await redis.delete(lock_key)


async def read_local_cache(
    itgs: Itgs, *, interactive_prompt_uid: str
) -> Optional[Union[bytes, io.BytesIO]]:
    """If the interactive prompt with the given uid is available in the local
    cache, returns it in the stored format, either streamed or fully loaded
    depending on its size. Otherwise, returns None.

    Note that this could be changed to always return an io.BytesIO - however,
    doing so would prevent the caller from determining whether the data is fully
    loaded or streamed, which can be useful for selecting the optimal way to
    manipulate it.

    The stored format can be efficiently converted to a response using
    convert_stored_format_to_response

    Args:
        itgs (Itgs): The integrations to (re)use
        interactive_prompt_uid (str): The UID of the interactive prompt to fetch

    Returns:
        (bytes, io.BytesIO, or None): The interactive prompt in the stored format,
            or None if it is not available in the local cache
    """
    cache = await itgs.local_cache()
    return cache.get(
        f"interactive_prompts:external:{interactive_prompt_uid}".encode("ascii"),
        read=True,
    )


async def write_local_cache(
    itgs: Itgs, *, interactive_prompt_uid: str, stored_format: Union[bytes, io.BytesIO]
) -> None:
    """Writes the interactive prompt in its stored format to the local cache.

    Args:
        itgs (Itgs): The integrations to (re)use
        interactive_prompt_uid (str): The UID of the interactive prompt to fetch
        stored_format (bytes or io.BytesIO): The interactive prompt in its stored format
    """
    cache = await itgs.local_cache()
    cache.set(
        f"interactive_prompts:external:{interactive_prompt_uid}".encode("ascii"),
        stored_format,
        read=not isinstance(stored_format, bytes),
        expire=86400 + random.randrange(0, 86400),
        tag="collab",
    )


async def delete_local_cache(itgs: Itgs, *, interactive_prompt_uid: str) -> None:
    """If the interactive prompt with the given uid is in the local cache, it is evicted

    Args:
        itgs (Itgs): The integrations to (re)use
        interactive_prompt_uid (str): The UID of the interactive prompt to evict
    """
    cache = await itgs.local_cache()
    cache.delete(
        f"interactive_prompts:external:{interactive_prompt_uid}".encode("ascii")
    )


def convert_interactive_prompt_to_stored_format(
    interactive_prompt: _InteractivePromptFromDB, f: io.BytesIO
) -> None:
    """Converts the interactive prompt to the stored format and writes it to the
    given stream. The stored format includes markers to allow customizable
    fields to be efficiently injected on the read.

    Args:
        itgs (Itgs): The integrations to (re)use
        interactive_prompt (_InteractivePromptFromDB): The interactive prompt to convert,
            in the way it was returned from the database. Note that the database already
            has the prompt serialized, so this can skip that step.
        out (io.BytesIO): The stream to write the stored format to. This must be
            seekable, and will be written to with a bunch of small writes.
    """
    # by putting all the varying stuff at the end, we can simplify how we do marks while
    # keeping to stored format extensible
    mark_start = f.tell()
    f.write(b"\x00\x00\x00\x00\x01")

    f.write(b'{"uid":"')
    f.write(interactive_prompt.uid.encode("ascii"))
    f.write(b'","prompt":')
    f.write(interactive_prompt.prompt.encode("ascii"))
    f.write(b',"duration_seconds":')
    f.write(str(interactive_prompt.duration_seconds).encode("ascii"))
    f.write(b',"journey_subcategory":')
    f.write(json.dumps(interactive_prompt.journey_subcategory).encode("ascii"))
    f.write(b',"session_uid":"')

    curr = f.tell()
    f.seek(mark_start)
    f.write((curr - mark_start - 5).to_bytes(4, "big", signed=False))
    f.seek(curr)

    f.write(
        b'\x00\x00\x00\x00\x02\x00\x00\x00\x09\x01","jwt":"\x00\x00\x00\x00\x03\x00\x00\x00\x02\x01"}'
    )


async def convert_stored_format_to_response(
    itgs: Itgs,
    *,
    interactive_prompt_jwt: str,
    interactive_prompt_session_uid: str,
    stored_format: io.BytesIO,
) -> AsyncIterator[bytes]:
    """Converts the interactive prompt in its stored format to a response, injecting
    the given data. The returned format is presented as bytes as they become available;
    this is marked async even though it's synchronous to prevent fastapi from moving
    this to a separate thread when used in combination with a streaming response

    Args:
        itgs (Itgs): The integrations to (re)use
        interactive_prompt_jwt (str): The JWT which will be injected into the
            returned interactive prompt so that the recipient can interact with it
        interactive_prompt_session_uid (str): The session UID which will be
            injected into the returned interactive prompt so that the recipient
            can interact with it
        stored_format (io.BytesIO): The interactive prompt in its stored format

    Returns:
        (Response): The interactive prompt as a response
    """
    while True:
        part_length_bytes = stored_format.read(4)
        if not part_length_bytes:
            return

        part_length = int.from_bytes(part_length_bytes, "big", signed=False)
        part_type = stored_format.read(1)
        part_contents = b"" if part_length == 0 else stored_format.read(part_length)

        if part_type == b"\x01":
            yield part_contents
        elif part_type == b"\x02":
            yield interactive_prompt_session_uid.encode("ascii")
        elif part_type == b"\x03":
            yield interactive_prompt_jwt.encode("ascii")
        else:
            raise ValueError(f"Unknown part type {part_type}")


async def get_interactive_prompt_from_db(
    itgs: Itgs,
    *,
    interactive_prompt_uid: str,
    consistency: Literal["strong", "weak", "none"] = "none",
) -> Optional[_InteractivePromptFromDB]:
    """Fetches the interactive prompt with the given uid from the database, or
    None if it doesn't exist.

    Args:
        itgs (Itgs): The integrations to (re)use
        interactive_prompt_uid (str): The UID of the interactive prompt to fetch
        consistency ('strong', 'weak', 'none'): The consistency level to use for the
            read. If 'none', on a failure this will retry with 'weak'.

    Returns:
        (_InteractivePromptFromDB or None): The interactive prompt, or None if it
            doesn't exist
    """
    conn = await itgs.conn()
    cursor = conn.cursor(consistency)

    response = await cursor.execute(
        """
        SELECT 
            interactive_prompts.prompt, 
            interactive_prompts.duration_seconds,
            journey_subcategories.internal_name
        FROM interactive_prompts
        LEFT OUTER JOIN journey_subcategories 
            ON EXISTS (
                SELECT 1 FROM journeys
                WHERE journeys.interactive_prompt_id = interactive_prompts.id
                  AND journeys.journey_subcategory_id = journey_subcategories.id
            )
        WHERE
            interactive_prompts.uid = ?
        ORDER BY journey_subcategories.uid ASC
        LIMIT 1
        """,
        (interactive_prompt_uid,),
    )
    if not response.results:
        if consistency == "none":
            return await get_interactive_prompt_from_db(
                itgs, interactive_prompt_uid=interactive_prompt_uid, consistency="weak"
            )
        return None

    return _InteractivePromptFromDB(
        uid=interactive_prompt_uid,
        prompt=response.results[0][0],
        duration_seconds=response.results[0][1],
        journey_subcategory=response.results[0][2],
    )


async def evict_interactive_prompt(itgs: Itgs, *, interactive_prompt_uid: str) -> None:
    """Evicts the interactive prompt with the given uid from all caches.

    Args:
        itgs (Itgs): The integrations to (re)use
        interactive_prompt_uid (str): The UID of the interactive prompt to evict
    """
    encoded_uid = interactive_prompt_uid.encode("ascii")
    message = b"\x00" + len(encoded_uid).to_bytes(4, "big", signed=False) + encoded_uid

    redis = await itgs.redis()
    await redis.publish(b"ps:interactive_prompts:push_cache", message)


async def push_interactive_prompt_to_caches(
    itgs: Itgs, *, interactive_prompt_uid: str, stored_format: bytes
):
    """Pushes the given stored representation of the interactive prompt with the
    given uid to all caches. The stored format must be in memory for this operation.

    Args:
        itgs (Itgs): The integrations to (re)use
        interactive_prompt_uid (str): The UID of the interactive prompt to push
        stored_format (bytes): The stored format of the interactive prompt
    """
    encoded_uid = interactive_prompt_uid.encode("ascii")
    message = (
        b"\x01"
        + len(encoded_uid).to_bytes(4, "big", signed=False)
        + encoded_uid
        + stored_format
    )

    redis = await itgs.redis()
    await redis.publish(b"ps:interactive_prompts:push_cache", message)


waiting_for_cache: Dict[str, List[asyncio.Event]] = {}
"""This mutable dictionary maps from keys of interactive prompt uids to a list of events
which should be set when we recieve a message from another instance about that
prompt, after it's been updated. The events are set once and then the list is
removed from the dictionary. This isn't cleaned by the cache push loop unless
a relevant message is received, so those adding to this dictionary should
have timeouts to clean up after themselves if they don't receive a message
"""


async def cache_push_loop() -> NoReturn:
    """Loops until the perpetual pub sub connection is closed, constantly listening
    for messages from (other) instances about interactive prompts that have been
    updated, and purging or updating our cache appropriately. This should be a
    background task that is started when the server starts, as it will mostly
    idle.
    """
    try:
        async with pps.PPSSubscription(
            pps.instance, "ps:interactive_prompts:push_cache", "ip-cpl"
        ) as sub:
            async for raw_message_bytes in sub:
                raw_message = io.BytesIO(raw_message_bytes)
                is_evict_message = raw_message.read(1) == b"\x00"
                encoded_uid_length = int.from_bytes(
                    raw_message.read(4), "big", signed=False
                )
                encoded_uid = raw_message.read(encoded_uid_length)
                uid = encoded_uid.decode("ascii")

                async with Itgs() as itgs:
                    if is_evict_message:
                        await delete_local_cache(itgs, interactive_prompt_uid=uid)
                    else:
                        stored_format = raw_message.read()
                        await write_local_cache(
                            itgs,
                            interactive_prompt_uid=uid,
                            stored_format=stored_format,
                        )

                        if uid in waiting_for_cache:
                            cp_list = list(waiting_for_cache[uid])
                            del waiting_for_cache[uid]
                            for event in cp_list:
                                event.set()
    except Exception as e:
        if pps.instance.exit_event.is_set() and isinstance(e, pps.PPSShutdownException):
            return
        await handle_error(e)
    finally:
        print("interactive_prompts read_one_external cache_push_loop exiting")
