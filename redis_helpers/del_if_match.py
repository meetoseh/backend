from typing import Optional, List, Union
import hashlib
import time
import redis.asyncio.client

DEL_IF_MATCH_LUA_SCRIPT = """
local key = KEYS[1]
local val = ARGV[1]

if redis.call("GET", key) == val then
    return redis.call("DEL", key)
end

return 0
"""

DEL_IF_MATCH_LUA_SCRIPT_HASH = hashlib.sha1(
    DEL_IF_MATCH_LUA_SCRIPT.encode("utf-8")
).hexdigest()


_last_del_if_match_ensured_at: Optional[float] = None


async def ensure_del_if_match_script_exists(
    redis: redis.asyncio.client.Redis, *, force: bool = False
) -> None:
    """Ensures the del_if_match lua script is loaded into redis."""
    global _last_del_if_match_ensured_at

    now = time.time()
    if (
        not force
        and _last_del_if_match_ensured_at is not None
        and (now - _last_del_if_match_ensured_at < 5)
    ):
        return

    loaded: List[bool] = await redis.script_exists(DEL_IF_MATCH_LUA_SCRIPT_HASH)
    if not loaded[0]:
        correct_hash = await redis.script_load(DEL_IF_MATCH_LUA_SCRIPT)
        assert (
            correct_hash == DEL_IF_MATCH_LUA_SCRIPT_HASH
        ), f"{correct_hash=} != {DEL_IF_MATCH_LUA_SCRIPT_HASH=}"

    if _last_del_if_match_ensured_at is None or _last_del_if_match_ensured_at < now:
        _last_del_if_match_ensured_at = now


async def del_if_match(
    redis: redis.asyncio.client.Redis, key: Union[str, bytes], val: Union[str, bytes]
) -> Optional[bool]:
    """Deletes the string key if its value matches the given value, and does
    nothing otherwise.

    Args:
        redis (redis.asyncio.client.Redis): The redis client
        key (str, bytes): The key to delete
        val (str, bytes): The value to compare against

    Returns:
        bool, None: True if the key was deleted, False otherwise. None if executed
            within a transaction, since the result is not known until the
            transaction is executed.

    Raises:
        NoScriptError: If the script is not loaded into redis
    """
    res = await redis.evalsha(DEL_IF_MATCH_LUA_SCRIPT_HASH, 1, key, val)  # type: ignore
    if res is redis:
        return None
    assert isinstance(res, int), res
    return bool(res)
