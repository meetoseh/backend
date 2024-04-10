import secrets
from typing import Optional, Union
from error_middleware import handle_warning
from itgs import Itgs
from contextlib import asynccontextmanager
import asyncio
import time
import socket
from loguru import logger as logging

from redis_helpers.acquire_lock import acquire_lock_safe
from redis_helpers.release_lock import release_lock_safe


class LockHeldError(Exception):
    """Raised when a lock is already held by another process"""

    def __init__(self, key):
        super().__init__(f"Lock {key=} is already held by another process")


@asynccontextmanager
async def basic_redis_lock(
    itgs: Itgs,
    key: Union[str, bytes],
    *,
    spin: bool = False,
    timeout: Optional[float] = None,
):
    """Uses redis for a very basic lock on the given key, releasing it when done.

    If the lock is currently taken, in order to reduce the need for human intervention
    after SIGKILLs, the following rules are used to determine if the lock can be stolen:

    - If the lock has been held the lock for at least 1m a warning is emitted.
      If they've held the lock for at least 2m, a different warning is emitted
      and a 5m expiration is set on the lock.

    Args:
        itgs (Itgs): The integrations to (re)use
        key (str, bytes): The redis key to use for the lock
        spin (bool): Whether to spin while waiting for the lock to be released,
            or to just raise an exception. Defaults to False. Requires that gd
            be specified to avoid spinning while a term signal is received.
        timeout (float): The maximum amount of time to wait for the lock before
            yielding without the lock
    """
    if isinstance(key, str):
        key = key.encode("utf-8")

    my_hostname = ("web-" + socket.gethostname()).encode("utf-8")
    lock_id = secrets.token_urlsafe(16).encode("utf-8")
    started_acquiring_at = time.perf_counter()
    while True:
        logging.debug(f"basic_redis_lock: acquiring lock {key=} {lock_id=} {timeout=}")
        lock_result = await acquire_lock_safe(
            itgs, key, my_hostname, int(time.time()), lock_id
        )
        if lock_result.error_type is None:
            logging.debug(f"basic_redis_lock: acquired lock {key=} {lock_id=}")
            break

        if lock_result.error_type == "already_held":
            logging.warning(f"basic_redis_lock: already held lock {key=} {lock_id=}")
            await handle_warning(
                f"{__name__}:already_held",
                f"lock {key=} was acquired without a success response",
            )
            break

        logging.info(
            f"basic_redis_lock: waiting for lock {key=} {lock_id=}: {lock_result=}, {spin=}, {timeout=}"
        )

        if not spin:
            raise LockHeldError(key)

        if (
            timeout is not None
            and (time.perf_counter() - started_acquiring_at) > timeout
        ):
            logging.info(
                f"basic_redis_lock: timed out waiting for lock {key=}, {lock_id=}, treating as if acquired"
            )
            try:
                yield
            finally:
                logging.debug(
                    f"basic_redis_lock: not releasing {key=} since we didn't acquire it"
                )
            return

        try:
            await asyncio.sleep(0.1)
        except (InterruptedError, KeyboardInterrupt):
            logging.info(
                f"basic_redis_lock: interrupt received while waiting for lock {key=}, {lock_id=}"
            )

    try:
        yield
    finally:
        logging.debug(f"basic_redis_lock: releasing {key=} {lock_id=}")
        await release_lock_safe(itgs, key, lock_id)
        logging.debug(f"basic_redis_lock: released {key=} {lock_id=}")
