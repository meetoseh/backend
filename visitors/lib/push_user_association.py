from itgs import Itgs
from redis.exceptions import NoScriptError
import hashlib

PUSH_VISITOR_ASSOCIATION_LUA = """
local queue_key = KEYS[1]
local lock_key = KEYS[2]
local queue_msg = ARGV[1]

if not redis.call("SET", lock_key, "1", "EX", 60, "NX") then
    return -1
end

local queue_length = redis.call("LLEN", queue_key)
if queue_length > 5000 then
    return -2
end

redis.call("RPUSH", queue_key, queue_msg)
return queue_length
"""

PUSH_VISITOR_ASSOCIATION_SHA = hashlib.sha1(
    PUSH_VISITOR_ASSOCIATION_LUA.encode("utf-8")
).hexdigest()


async def push_visitor_association(
    itgs: Itgs, queue_key: bytes, lock_key: bytes, msg: bytes
):
    """Pushes the given message to the given queue, so long as we are able to
    SETNX the lock key for 60 seconds and there are 5000 or fewer messages in
    the queue.

    This is done in such a way that it is completely concurrency safe, with
    the minor caveat that during a failover it may expire the lock early.
    """
    redis = await itgs.redis()
    try:
        await redis.evalsha(PUSH_VISITOR_ASSOCIATION_SHA, 2, queue_key, lock_key, msg)
    except NoScriptError:
        correct_sha = await redis.script_load(PUSH_VISITOR_ASSOCIATION_LUA)
        assert (
            correct_sha == PUSH_VISITOR_ASSOCIATION_SHA
        ), f"{correct_sha=} != {PUSH_VISITOR_ASSOCIATION_SHA=}"
        await redis.evalsha(PUSH_VISITOR_ASSOCIATION_SHA, 2, queue_key, lock_key, msg)
