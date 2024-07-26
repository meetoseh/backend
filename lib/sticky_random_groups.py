import asyncio
import io
import secrets
import socket
import time
from typing import Literal, Optional, cast, overload
from itgs import Itgs
import hmac
import randomgen
from lifespan import lifespan_handler
import perpetual_pub_sub as pps


@overload
async def check_if_user_in_sticky_random_group(
    itgs: Itgs,
    /,
    *,
    user_sub: str,
    group_name: str,
    create_if_not_exists: Literal[False],
) -> Optional[bool]: ...


@overload
async def check_if_user_in_sticky_random_group(
    itgs: Itgs,
    /,
    *,
    user_sub: str,
    group_name: str,
    create_if_not_exists: Literal[True],
) -> bool: ...


async def check_if_user_in_sticky_random_group(
    itgs: Itgs, /, *, user_sub: str, group_name: str, create_if_not_exists: bool
) -> Optional[bool]:
    """
    Determines if the user with the given sub is in the group with the given
    name. Group information is cached locally (cooperatively); on cache hits,
    this does not require a network call. Generally, this updates within
    milliseconds of the group changing, though it does assume groups don't
    change too often (so certain races around instance bootup and group
    changes are very unlikely and can be ignored)

    Args:
        itgs (Itgs): the integrations to (re)use
        user_sub (str): the user's sub to check for
        group_name (str): the group to check in
        create_if_not_exists (bool): if the group should be created if it
            doesn't exist (usually, True). We will send a message to slack
            if we create a new group.

    Returns:
        (bool, None): whether the user is in the group, if the group exists,
            otherwise None
    """
    group_number = await get_sticky_random_group_number_from_local_cache(
        itgs, group_name=group_name
    )
    if group_number is not None:
        return check_sticky_random_group_contains(
            group_number=group_number, user_sub=user_sub
        )

    group_number = await get_sticky_random_group_number_from_source(
        itgs, group_name=group_name, read_consistency="none"
    )
    if group_number is None:
        if not create_if_not_exists:
            group_number = await get_sticky_random_group_number_from_source(
                itgs, group_name=group_name, read_consistency="weak"
            )
        else:
            group_number = await get_or_create_sticky_random_group_number(
                itgs, group_name=group_name
            )

    if group_number is None:
        return None

    await write_sticky_random_group_number_to_local_cache(
        itgs, group_name=group_name, group_number=group_number
    )
    return check_sticky_random_group_contains(
        group_number=group_number, user_sub=user_sub
    )


async def evict_sticky_random_group(
    itgs: Itgs, /, *, group_name: str, new_number: Optional[bytes] = None
) -> None:
    """Evicts the group number associated from the group name from all caches,
    optionally replacing it with a new group number.

    Args:
        itgs (Itgs): the integrations to (re)use
        group_name (str): the group to evict
        new_number (bytes, None): the new group number to replace it with, if
            any. If None, it is just deleted, not replaced
    """
    message = io.BytesIO()

    group_name_bytes = group_name.encode("utf-8")
    message.write(len(group_name_bytes).to_bytes(4, "big"))
    message.write(group_name_bytes)
    if new_number is None:
        message.write(b"\x00")
    else:
        message.write(b"\x01")
        message.write(new_number)

    redis = await itgs.redis()
    await redis.publish(b"ps:sticky_random_groups", message.getvalue())


async def get_sticky_random_group_number_from_local_cache(
    itgs: Itgs, /, *, group_name: str
) -> Optional[bytes]:
    """Gets the group number associated with the group with the given name
    from the local cache, if it is there, otherwise returns None
    """
    cache = await itgs.local_cache()
    return cast(
        Optional[bytes],
        cache.get(f"sticky_random_group_number:{group_name}".encode("utf-8")),
    )


async def write_sticky_random_group_number_to_local_cache(
    itgs: Itgs, /, *, group_name: str, group_number: bytes
) -> None:
    """Writes the group number associated with the group with the given
    name to the local cache.
    """
    cache = await itgs.local_cache()
    cache.set(
        f"sticky_random_group_number:{group_name}".encode("utf-8"),
        group_number,
        tag="collab",
        expire=86400,
    )


async def delete_sticky_random_group_number_from_local_cache(
    itgs: Itgs, /, *, group_name: str
) -> None:
    """Deletes the group number associated with the group with the given name
    from the local cache, if it is there, otherwise does nothing.
    """
    cache = await itgs.local_cache()
    cache.delete(f"sticky_random_group_number:{group_name}".encode("utf-8"))


def check_sticky_random_group_contains(*, group_number: bytes, user_sub: str) -> bool:
    """Checks if the sticky group with the given group number contains the
    user with the given sub. This always returns the same result for the same
    inputs.

    Generally, prefer `check_if_user_in_sticky_random_group` instead of this,
    which handles converting a group name to a group number for you.
    """
    shuffled_together_bytes = hmac.digest(
        group_number, user_sub.encode("utf-8"), "sha256"
    )
    shuffled_together_number = int.from_bytes(shuffled_together_bytes, "big")
    gen = randomgen.ChaCha(key=shuffled_together_number)
    token = gen.random_raw()
    assert isinstance(token, int), token
    bit = token & 1
    return bool(bit)


async def get_sticky_random_group_number_from_source(
    itgs: Itgs,
    /,
    *,
    group_name: str,
    read_consistency: Literal["none", "weak", "strong"],
) -> Optional[bytes]:
    """Gets the group number associated with the group with the given name,
    case insensitively, from the source of truth, if it already exists.

    Args:
        itgs (Itgs): the integrations to (re)use
        group_name (str): the group to get the number for

    Returns:
        (bytes, None): the group number, if it exists, otherwise None
    """
    conn = await itgs.conn()
    cursor = conn.cursor(read_consistency)
    response = await cursor.execute(
        "SELECT group_number_hex FROM sticky_random_groups WHERE name = ? COLLATE NOCASE",
        (group_name,),
    )
    if not response.results:
        return None

    group_number_hex = cast(str, response.results[0][0])
    return bytes.fromhex(group_number_hex)


async def get_or_create_sticky_random_group_number(
    itgs: Itgs, /, *, group_name: str
) -> bytes:
    """Creates a new sticky random group with the given name, if it doesn't
    already exist, and returns the group number associated with it.

    Args:
        itgs (Itgs): the integrations to (re)use
        group_name (str): the group to get or create the number for (case insensitive)
    """
    conn = await itgs.conn()
    cursor = conn.cursor("strong")

    response = await cursor.executeunified3(
        (
            (
                """
INSERT INTO sticky_random_groups (
    uid, name, group_number_hex, created_at
)
SELECT
    ?, ?, ?, ?
WHERE
    NOT EXISTS (
        SELECT 1 FROM sticky_random_groups AS srg WHERE srg.name = ? COLLATE NOCASE
    )
                """,
                (
                    f"oseh_srg_{secrets.token_urlsafe(16)}",
                    group_name,
                    secrets.token_hex(32),
                    time.time(),
                    group_name,
                ),
            ),
            (
                "SELECT group_number_hex FROM sticky_random_groups WHERE name = ? COLLATE NOCASE",
                (group_name,),
            ),
        ),
    )

    if response[0].rows_affected is not None and response[0].rows_affected > 0:
        slack = await itgs.slack()
        await slack.send_ops_message(
            f"`{socket.gethostname()}` created a new sticky random group with the name `{group_name}`"
        )

    assert response[1].results, response
    group_number_hex = cast(str, response[1].results[0][0])
    return bytes.fromhex(group_number_hex)


async def _handle_incoming_messages_forever():
    assert pps.instance is not None

    async with pps.PPSSubscription(
        pps.instance, "ps:sticky_random_groups", "srg_himf"
    ) as sub:
        async for message_raw in sub:
            message = io.BytesIO(message_raw)
            group_name_length = int.from_bytes(message.read(4), "big")
            group_name = message.read(group_name_length).decode("utf-8")
            message_type = int.from_bytes(message.read(1), "big")
            if message_type == 0:
                async with Itgs() as itgs:
                    await delete_sticky_random_group_number_from_local_cache(
                        itgs, group_name=group_name
                    )
                    continue

            assert message_type == 1, message_type
            group_number = message.read(32)
            async with Itgs() as itgs:
                await write_sticky_random_group_number_to_local_cache(
                    itgs, group_name=group_name, group_number=group_number
                )


@lifespan_handler
async def listen_for_sticky_random_group_changes_forever():
    task = asyncio.create_task(_handle_incoming_messages_forever())
    yield
