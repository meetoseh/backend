from itgs import Itgs


async def up(itgs: Itgs) -> None:
    """Removes old data for the special notification prompt now that it's replaced
    with the new public interactive prompts and the frontend has transitioned
    """
    local_cache = await itgs.local_cache()
    local_cache.delete(b"interactive_prompts:special:notification_time:uid")

    redis = await itgs.redis()
    await redis.delete(b"interactive_prompts:special:notification_time:uid")
