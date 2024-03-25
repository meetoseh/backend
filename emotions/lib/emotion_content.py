import secrets
from typing import (
    Callable,
    Coroutine,
    List,
    NoReturn as Never,
    Optional,
    cast as typing_cast,
)
from error_middleware import handle_error
from itgs import Itgs
from emotions.routes.read import Emotion
from pydantic import BaseModel, Field
import perpetual_pub_sub as pps
import asyncio
import random
from loguru import logger


class EmotionContentStatistics(BaseModel):
    emotion: Emotion = Field(description="The emotion these statistics are for")
    num_journeys: int = Field(
        description="The number of undeleted journeys that have this emotion"
    )


class CachedEmotionContentStatistics(BaseModel):
    stats: List[EmotionContentStatistics] = Field(
        description="The statistics on every emotion, sorted by the number of journeys in descending order"
    )


stats_listeners: List[
    Callable[[Optional[List[EmotionContentStatistics]]], Coroutine[None, None, None]]
] = []
"""Called when we retrieve a purge message from ourselves or
another instance modifying our cache. If the message included
the new statistics, or the statistics were able to be generated,
they are passed to the listener.
"""


async def get_emotion_content_statistics(itgs: Itgs) -> List[EmotionContentStatistics]:
    """Fetches the emotion content statistics from the nearest available source,
    filling intermediary sources as needed. This uses a dual-caching strategy
    that ensures that under normal circumstances, the number of cache misses does
    not depend on the number of backend instances.

    A basic locking mechanism is used to alleviate cache stampedes, as filling
    this cache can be very expensive.

    Args
        itgs (Itgs): The integrations to (re)use

    Returns:
        list[EmotionContentStatistics]: The statistics on every emotion, sorted
            by the number of journeys in descending order
    """
    req_id = secrets.token_urlsafe(4)
    logger.info(f"get_emotion_content_statistics assigned {req_id=}")

    result = await get_emotion_content_statistics_from_cache(itgs)
    if result is not None:
        logger.info(f"{req_id=} LOCAL CACHE HIT")
        return result

    result = await get_emotion_content_statistics_from_redis(itgs)
    if result is not None:
        logger.info(f"{req_id=} REMOTE CACHE HIT")
        await set_emotion_content_statistics_in_cache(itgs, stats=result)
        return result

    redis = await itgs.redis()
    lock_key = b"emotion_content_statistics:lock"
    got_lock = await redis.set(lock_key, b"1", nx=True, ex=10)
    if not got_lock:
        logger.debug(f"{req_id=} RECHECKING (failed to acquire lock)")
        stats: Optional[List[EmotionContentStatistics]] = None
        stats_event = asyncio.Event()

        async def on_stats(stats_: Optional[List[EmotionContentStatistics]]):
            nonlocal stats
            stats = stats_
            stats_event.set()

        my_stats_listeners = stats_listeners
        my_stats_listeners.append(on_stats)
        wait_task = asyncio.create_task(stats_event.wait())

        # have to double check now that we have listeners

        result = await get_emotion_content_statistics_from_cache(itgs)
        if result is not None:
            logger.info(
                f"{req_id=} LOCAL CACHE HIT (recheck after failed to acquire lock)"
            )
            my_stats_listeners.remove(on_stats)
            wait_task.cancel()
            return result

        result = await get_emotion_content_statistics_from_redis(itgs)
        if result is not None:
            logger.info(
                f"{req_id=} REMOTE CACHE HIT (recheck after failed to acquire lock)"
            )
            my_stats_listeners.remove(on_stats)
            wait_task.cancel()
            await set_emotion_content_statistics_in_cache(itgs, stats=result)
            return result

        if not wait_task.done():
            assert (
                stats_listeners is my_stats_listeners
            ), "stats_listener invoked but wait_task not done?"

        logger.debug(f"{req_id=} WAITING (failed to acquire lock)")
        try:
            await asyncio.wait_for(wait_task, timeout=10)
            if stats is not None:
                logger.info(f"{req_id} RECEIVED STATS FROM SUBSCRIPTION")
                return stats
            else:
                logger.warning(f"{req_id} wait_task done but stats is None")
        except asyncio.TimeoutError as e:
            my_stats_listeners.remove(on_stats)
            wait_task.cancel()
            await handle_error(
                e, extra_info="while waiting for emotion_content_statistics"
            )

        logger.debug(f"{req_id=} FALLTHROUGH (failed to acquire lock, timed out)")
    else:
        logger.debug(f"{req_id=} RECHECKING (acquired lock)")
    # need to recheck with the lock
    result = await get_emotion_content_statistics_from_cache(itgs)
    if result is not None:
        logger.info(f"{req_id=} LOCAL CACHE HIT (recheck after acquired lock)")
        if got_lock:
            await redis.delete(lock_key)
        return result

    result = await get_emotion_content_statistics_from_redis(itgs)
    if result is not None:
        logger.info(f"{req_id=} REMOTE CACHE HIT (recheck after acquired lock)")
        await set_emotion_content_statistics_in_cache(itgs, stats=result)
        if got_lock:
            await redis.delete(lock_key)
        return result

    try:
        result = await get_emotion_content_statistics_from_db(itgs)
        logger.info(f"{req_id=} DB HIT")
        await set_emotion_content_statistics_in_cache(itgs, stats=result)
        await update_emotion_content_statistics_everywhere(itgs, stats=result)
        return result
    finally:
        await redis.delete(lock_key)


async def get_emotion_content_statistics_from_redis(
    itgs: Itgs,
) -> Optional[List[EmotionContentStatistics]]:
    redis = await itgs.redis()
    raw = await redis.get(b"emotion_content_statistics")
    if raw is None:
        return None
    parsed = CachedEmotionContentStatistics.model_validate_json(raw)
    return parsed.stats


async def get_emotion_content_statistics_from_cache(
    itgs: Itgs,
) -> Optional[List[EmotionContentStatistics]]:
    cache = await itgs.local_cache()
    raw = typing_cast(bytes, cache.get(b"emotion_content_statistics"))
    if raw is None:
        return None
    parsed = CachedEmotionContentStatistics.model_validate_json(raw)
    return parsed.stats


async def get_emotion_content_statistics_from_db(
    itgs: Itgs,
) -> List[EmotionContentStatistics]:
    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    response = await cursor.execute(
        "SELECT emotions.word, emotions.antonym FROM emotions"
    )
    all_emotions: List[Emotion] = [
        Emotion(word=word, antonym=antonym)
        for (word, antonym) in (response.results or [])
    ]
    if not all_emotions:
        return []

    response = await cursor.execute(
        """
        SELECT
            emotions.word,
            emotions.antonym,
            COUNT(*)
        FROM emotions, journey_emotions, journeys
        WHERE
            emotions.id = journey_emotions.emotion_id
            AND journey_emotions.journey_id = journeys.id
            AND journeys.deleted_at IS NULL
            AND NOT EXISTS (
                SELECT 1 FROM course_journeys
                WHERE course_journeys.journey_id = journeys.id
            )
        GROUP BY emotions.id
        ORDER BY COUNT(*) DESC, emotions.word ASC
        """
    )
    stats: List[EmotionContentStatistics] = []

    missing_words = set((e.word, e.antonym) for e in all_emotions)
    for word, antonym, num_journeys in response.results or []:
        stats.append(
            EmotionContentStatistics(
                emotion=Emotion(word=word, antonym=antonym), num_journeys=num_journeys
            )
        )
        missing_words.discard((word, antonym))

    for word, antonym in sorted(missing_words):
        stats.append(
            EmotionContentStatistics(
                emotion=Emotion(word=word, antonym=antonym), num_journeys=0
            )
        )

    return stats


async def set_emotion_content_statistics_in_cache(
    itgs: Itgs, *, stats: Optional[List[EmotionContentStatistics]]
):
    cache = await itgs.local_cache()
    if stats is not None:
        raw = (
            CachedEmotionContentStatistics(stats=stats)
            .model_dump_json()
            .encode("utf-8")
        )
        cache.set(
            b"emotion_content_statistics",
            raw,
            expire=random.randint(60 * 60 * 24, 60 * 60 * 24 * 2),
            tag="collab",
        )
    else:
        cache.delete(b"emotion_content_statistics")


async def set_emotion_content_statistics_in_redis(
    itgs: Itgs, *, stats: Optional[List[EmotionContentStatistics]]
):
    redis = await itgs.redis()
    if stats is not None:
        raw = (
            CachedEmotionContentStatistics(stats=stats)
            .model_dump_json()
            .encode("utf-8")
        )
        await redis.set(
            b"emotion_content_statistics",
            raw,
            ex=random.randint(60 * 60 * 24, 60 * 60 * 24 * 2),
        )
    else:
        await redis.delete(b"emotion_content_statistics")


class EmotionContentPurgeMessage(BaseModel):
    replace_stats: Optional[List[EmotionContentStatistics]] = Field(
        description=(
            "If present, instead of just purging the cache, replace "
            "the cache with these statistics"
        )
    )


async def update_emotion_content_statistics_everywhere(
    itgs: Itgs, *, stats: List[EmotionContentStatistics]
):
    """Refreshes the emotion content statistics in the distributed cache
    and on all local caches to reflect the given statistics. This is
    guarranteed to eventually update the stats to the last given value,
    however it returns before that happens. In particular, this will
    generally return before our own local cache is updated.

    Args:
        itgs (Itgs): The integrations to (re)use
        stats (List[EmotionContentStatistics]): The statistics to update
            to
    """
    msg = (
        EmotionContentPurgeMessage(replace_stats=stats)
        .model_dump_json()
        .encode("utf-8")
    )
    new_stats = (
        CachedEmotionContentStatistics(stats=stats).model_dump_json().encode("utf-8")
    )

    redis = await itgs.redis()
    async with redis.pipeline(transaction=True) as pipe:
        pipe.multi()
        await pipe.set(
            b"emotion_content_statistics",
            new_stats,
            ex=random.randint(60 * 60 * 24, 60 * 60 * 24 * 2),
        )
        await pipe.publish("ps:emotion_content_statistics:push_cache", msg)
        await pipe.execute()


async def purge_emotion_content_statistics_everywhere(
    itgs: Itgs, *, emotions: Optional[List[str]] = None
):
    """Purges emotion content statistics from the distributed cache and
    all local caches. The cache will be filled again with the latest
    statistics from the database on the next request.

    Args:
        itgs (Itgs): The integrations to (re)use
        emotions (list[str] or None): If the callee knows that only
            certain emotions statistics may have changed, they can
            specify them here. Currently unused, but left open for
            future use.
    """
    message = (
        EmotionContentPurgeMessage(replace_stats=None).model_dump_json().encode("utf-8")
    )

    redis = await itgs.redis()
    async with redis.pipeline(transaction=True) as pipe:
        pipe.multi()
        await pipe.delete(b"emotion_content_statistics")
        await pipe.publish("ps:emotion_content_statistics:push_cache", message)
        await pipe.execute()


async def handle_emotion_content_purge_message(
    itgs: Itgs, *, message: EmotionContentPurgeMessage
):
    """Handles receiving a emotion content statistics purge message over
    the channel. This updates just local caches, since the distributed
    cache must be updated prior to sending the message. This will inform
    any local listeners.

    Args:
        itgs (Itgs): The integrations to (re)use
        message (EmotionContentPurgeMessage): The message to handle
    """
    global stats_listeners
    listeners = stats_listeners
    stats_listeners = []

    await set_emotion_content_statistics_in_cache(itgs, stats=message.replace_stats)
    for listener in listeners:
        try:
            await listener(message.replace_stats)
        except Exception as e:
            await handle_error(
                e, extra_info="while handling emotion content purge message listener"
            )


async def emotion_content_statistics_purge_cache_loop() -> Never:
    """Loops indefinitely, listening for messages from the channel to
    purge the emotion content statistics cache.
    """
    assert pps.instance is not None

    async with pps.PPSSubscription(
        pps.instance, "ps:emotion_content_statistics:push_cache", "emotion_content"
    ) as subscription:
        async for raw_message in subscription:
            message = EmotionContentPurgeMessage.model_validate_json(raw_message)
            async with Itgs() as itgs:
                await handle_emotion_content_purge_message(itgs, message=message)
