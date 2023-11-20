from typing import Union
from itgs import Itgs
from contextlib import asynccontextmanager
import asyncio
import time


class LockHeldError(Exception):
    """Raised when a lock is already held by another process"""

    def __init__(self, key):
        super().__init__(f"Lock {key=} is already held by another process")


@asynccontextmanager
async def basic_redis_lock(
    itgs: Itgs, key: Union[str, bytes], *, spin: bool = False, timeout: float = 5
):
    """Uses redis for a very basic lock on the given key, releasing it when done

    Args:
        itgs (Itgs): The integrations to (re)use
        key (str, bytes): The redis key to use for the lock
        spin (bool): Whether to spin while waiting for the lock to be released,
            or to just raise an exception. Defaults to False.
        timeout (float): maximum time to spin before raising an exception. Ignored
            if spin is False. Defaults to 5. Accurate to about 0.1 seconds.
    """
    redis = await itgs.redis()

    started_spinning_at = time.perf_counter()
    while True:
        success = await redis.set(key, "1", nx=True, ex=86400)
        if success:
            break
        if not spin:
            raise LockHeldError(key)
        if time.perf_counter() - started_spinning_at > timeout:
            raise LockHeldError(key)
        await asyncio.sleep(0.1)

    try:
        yield
    finally:
        await redis.delete(key)
