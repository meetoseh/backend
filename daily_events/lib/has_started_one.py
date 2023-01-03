"""This module handles checking if a user has already started a journey within
a daily event when they don't have the pro entitlement, which they can only do
once per daily event.

This check is along the critical path and is hence cached locally and in redis
via a collaborative mechanism, ensuring that for the majority of requests no
network traffic is required.
"""
from pydantic import BaseModel, Field
from typing import NoReturn
import perpetual_pub_sub as pps
from itgs import Itgs
from redis.exceptions import NoScriptError
import hashlib


async def has_started_one(itgs: Itgs, *, user_sub: str, daily_event_uid: str) -> bool:
    """Checks if a user has already started a journey within a daily event. This
    will check the local cache first, before falling back to redis.

    Args:
        itgs (Itgs): The integrations to (re)use
        user_sub (str): The sub of the user to check
        daily_event_uid (str): The uid of the daily event to check

    Returns:
        bool: True if the user has already started a journey within the daily
            event, otherwise False
    """
    cache_key = f"daily_events:has_started_one:{daily_event_uid}:{user_sub}".encode(
        "utf-8"
    )

    local_cache = await itgs.local_cache()
    cached = local_cache.get(cache_key)
    if cached is not None:
        return bool(int(str(cached, "ascii")))

    redis = await itgs.redis()

    async with redis.pipeline() as pipe:
        pipe.multi()
        await pipe.set(cache_key, b"0", ex=60 * 60 * 24 * 2, nx=True)
        await pipe.get(cache_key)
        did_set, cached = await pipe.execute()

    started_one = bool(int(str(cached, "ascii")))
    local_cache.set(
        cache_key,
        bytes(str(int(started_one)), "ascii"),
        expire=60 * 60 * 24 * 2,
        tag="collab",
    )
    if did_set:
        # technically this can still race, wcyd, worst case occassionally a user
        # gets an extra journey
        message = DailyEventsHasStartedOnePubSubMessage(
            daily_event_uid=daily_event_uid, user_sub=user_sub, started_one=False
        )
        await redis.publish(
            b"ps:daily_events:has_started_one", message.json().encode("utf-8")
        )

    return started_one


SET_AND_EXPIRE_IF_UNSET_OR_ZERO_SCRIPT = """
local key = KEYS[1]

local value = redis.call("GET", key)
if value == false or value == "0" then
    redis.call("SET", key, "1", "EX", 60 * 60 * 24 * 2)
    return 1
else
    return 0
end
"""

SET_AND_EXPIRE_IF_UNSET_OR_ZERO_SCRIPT_HASH = hashlib.sha1(
    SET_AND_EXPIRE_IF_UNSET_OR_ZERO_SCRIPT.encode("utf-8")
).hexdigest()


async def set_and_expire_if_unset_or_zero(itgs: Itgs, key: str) -> bool:
    """A concurrency safe equivalent of the following:

    ```py
    redis = await itgs.redis()
    value = await redis.get(key)
    if value is None or value == b"0":
        await redis.set(key, b"1", ex=60 * 60 * 24 * 2)
        return True
    else:
        return False
    ```

    in other words, this will set the value to 1 if it's currently unset or 0,
    and will return True if it was set, otherwise it will return False. If
    the key is set, it is configured to expire in 2 days.

    Args:
        itgs (Itgs): The integrations to (re)
        key (str): The key to set
    """
    redis = await itgs.redis()

    try:
        res = await redis.evalsha(SET_AND_EXPIRE_IF_UNSET_OR_ZERO_SCRIPT_HASH, 1, key)
    except NoScriptError:
        true_sha = await redis.script_load(SET_AND_EXPIRE_IF_UNSET_OR_ZERO_SCRIPT)
        assert (
            true_sha == SET_AND_EXPIRE_IF_UNSET_OR_ZERO_SCRIPT_HASH
        ), f"{true_sha=} != {SET_AND_EXPIRE_IF_UNSET_OR_ZERO_SCRIPT_HASH=}"
        res = await redis.evalsha(SET_AND_EXPIRE_IF_UNSET_OR_ZERO_SCRIPT_HASH, 1, key)

    return int(res) == 1


async def on_started_one(
    itgs: Itgs, *, user_sub: str, daily_event_uid: str, force: bool = False
) -> bool:
    """Updates the necessary caches to indicate that a user has started a
    journey within a daily event.

    Args:
        itgs (Itgs): The integrations to (re)use
        user_sub (str): The sub of the user who has started a journey
        daily_event_uid (str): The uid of the daily event that the user has
            started a journey within
        force (bool): If True, this will set the value even if it's already set,
            and always return True. If False, this will do nothing if the value
            is already 1, and will only return True if the value was 0 before
            and is now 1. Defaults to False.

    Returns:
        bool: True if the value was updated, otherwise False
    """
    cache_key = f"daily_events:has_started_one:{daily_event_uid}:{user_sub}".encode(
        "utf-8"
    )

    redis = await itgs.redis()
    if force:
        await redis.set(cache_key, b"1", ex=60 * 60 * 24 * 2)
    else:
        success = await set_and_expire_if_unset_or_zero(itgs, cache_key)
        if not success:
            return False

    message = DailyEventsHasStartedOnePubSubMessage(
        daily_event_uid=daily_event_uid, user_sub=user_sub, started_one=True
    )
    await redis.publish(
        b"ps:daily_events:has_started_one", message.json().encode("utf-8")
    )
    return True


async def purge_loop() -> NoReturn:
    """Loops infinitely, handling messages from other instances that require us
    to update our local cache of whether a user has started a journey within a
    daily event.
    """
    async with pps.PPSSubscription(
        pps.instance, "ps:daily_events:has_started_one", "de_hso"
    ) as sub:
        async for raw_message in sub:
            message = DailyEventsHasStartedOnePubSubMessage.parse_raw(
                raw_message, content_type="application/json"
            )

            async with Itgs() as itgs:
                local_cache = await itgs.local_cache()
                local_cache.set(
                    f"daily_events:has_started_one:{message.daily_event_uid}:{message.user_sub}".encode(
                        "utf-8"
                    ),
                    bytes(str(int(message.started_one)), "ascii"),
                    expire=60 * 60 * 24 * 2,
                    tag="collab",
                )


class DailyEventsHasStartedOnePubSubMessage(BaseModel):
    daily_event_uid: str = Field(
        description="The UID of the daily event that the user has (not) started a journey in"
    )
    user_sub: str = Field(
        description="The sub of the user without a pro entitlement who has (not) started a journey"
    )
    started_one: bool = Field(
        description="True if the user has started a journey, otherwise False"
    )
