from typing import Optional, List
import hashlib
import time
import redis.asyncio.client

HINCRBY_IF_EXISTS_LUA_SCRIPT = """
local hash_key = KEYS[1]
local hash_field = KEYS[2]
local value = ARGV[1]

if redis.call("HEXISTS", hash_key, hash_field) == 1 then
    return redis.call("HINCRBY", hash_key, hash_field, value)
end

return false
"""

HINCRBY_IF_EXISTS_LUA_SCRIPT_HASH = hashlib.sha1(
    HINCRBY_IF_EXISTS_LUA_SCRIPT.encode("utf-8")
).hexdigest()


_last_hincrby_if_exists_ensured_at: Optional[float] = None


async def ensure_hincrby_if_exists_script_exists(
    redis: redis.asyncio.client.Redis, *, force: bool = False
) -> None:
    """Ensures the hincrby_if_exists lua script is loaded into redis."""
    global _last_hincrby_if_exists_ensured_at

    now = time.time()
    if (
        not force
        and _last_hincrby_if_exists_ensured_at is not None
        and (now - _last_hincrby_if_exists_ensured_at < 5)
    ):
        return

    loaded: List[bool] = await redis.script_exists(HINCRBY_IF_EXISTS_LUA_SCRIPT_HASH)
    if not loaded[0]:
        correct_hash = await redis.script_load(HINCRBY_IF_EXISTS_LUA_SCRIPT)
        assert (
            correct_hash == HINCRBY_IF_EXISTS_LUA_SCRIPT_HASH
        ), f"{correct_hash=} != {HINCRBY_IF_EXISTS_LUA_SCRIPT_HASH=}"

    if _last_hincrby_if_exists_ensured_at is None or _last_hincrby_if_exists_ensured_at < now:
        _last_hincrby_if_exists_ensured_at = now


async def hincrby_if_exists(
    redis: redis.asyncio.client.Redis, key: bytes, field: bytes, val: int
) -> Optional[int]:
    """Increments the field in the given key if the field exists in the hash,
    as if by HEXISTS key field


    Args:
        redis (redis.asyncio.client.Redis): The redis client
        key (bytes): The key to update
        field (bytes): The field to update
        val (int): The value to increment by

    Returns:
        int, None: The new value if an increment occurred, None if no increment. 
            None if executed within a transaction, since the result is not known
            until the transaction is executed.

    Raises:
        NoScriptError: If the script is not loaded into redis
    """
    res = await redis.evalsha(HINCRBY_IF_EXISTS_LUA_SCRIPT_HASH, 2, key, field, val)  # type: ignore
    if res is redis:
        return None
    if res is None:
        return None
    assert isinstance(res, int)
    return res
