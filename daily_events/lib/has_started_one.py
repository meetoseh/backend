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
    local_cache.set(cache_key, bytes(str(int(started_one)), "ascii"), tag="collab")
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


async def on_started_one(itgs: Itgs, *, user_sub: str, daily_event_uid: str) -> None:
    """Updates the necessary caches to indicate that a user has started a
    journey within a daily event.

    Args:
        itgs (Itgs): The integrations to (re)use
        user_sub (str): The sub of the user who has started a journey
        daily_event_uid (str): The uid of the daily event that the user has
            started a journey within
    """
    redis = await itgs.redis()
    await redis.set(
        f"daily_events:has_started_one:{daily_event_uid}:{user_sub}".encode("utf-8"),
        b"1",
    )

    message = DailyEventsHasStartedOnePubSubMessage(
        daily_event_uid=daily_event_uid, user_sub=user_sub, started_one=True
    )
    await redis.publish(
        b"ps:daily_events:has_started_one", message.json().encode("utf-8")
    )


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
