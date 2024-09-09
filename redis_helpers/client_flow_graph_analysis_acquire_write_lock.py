from dataclasses import dataclass
from typing import Any, Literal, Optional, List, Union
import hashlib
import time
import redis.asyncio.client

from itgs import Itgs
from redis_helpers.run_with_prep import run_with_prep

CLIENT_FLOW_GRAPH_ANALYSIS_ACQUIRE_WRITE_LOCK_LUA_SCRIPT = """
local graph_id = ARGV[1]
local uid_if_initialize = ARGV[2]
local lock_uid_if_acquired = ARGV[3]
local now = tonumber(ARGV[4])
local min_ttl = tonumber(ARGV[5])

local lock_time = 300
local data_cache_time = 3600

local version_str = redis.call("GET", "client_flow_graph_analysis:version")
local version = 0
if version_str == false then
    redis.call("SET", "client_flow_graph_analysis:version", 0)
    version_str = '0'
else
    version = tonumber(version_str)
end

local key_base = 'client_flow_graph_analysis:' .. graph_id .. ':' .. version_str
local writer_lock_key = key_base .. ':writer'
local readers_lock_key = key_base .. ':readers'

local writers = redis.call('EXISTS', writer_lock_key)
redis.call('ZREMRANGEBYSCORE', readers_lock_key, '-inf', now)
local readers = redis.call('ZCARD', readers_lock_key)
if writers > 0 or readers > 0 then
    return {3, version, readers, writers}
end


local meta_key = key_base .. ':meta'

local meta_expires_at_str = redis.call('HGET', meta_key, 'expires_at')
local meta_expires_at = false
local lock_expires_at = now + lock_time
if meta_expires_at_str ~= false then
    meta_expires_at = tonumber(meta_expires_at_str)
    if lock_expires_at > meta_expires_at then
        lock_expires_at = meta_expires_at
    end
end

if meta_expires_at == false or meta_expires_at - now < min_ttl then
    redis.call('HMSET', meta_key, 'uid', uid_if_initialize, 'initialized_at', now, 'expires_at', now + data_cache_time)
    redis.call('EXPIREAT', meta_key, now + data_cache_time)
    redis.call('SET', writer_lock_key, lock_uid_if_acquired)
    redis.call('EXPIREAT', writer_lock_key, lock_expires_at)
    redis.call(
        'PUBLISH',
        'ps:client_flow_graph_analysis:lock_changed',
        struct.pack('>I4', string.len(graph_id)) 
            .. graph_id 
            .. struct.pack('>I2', 0)
            .. struct.pack('>I1', 1)
    )
    local replaced_stale = 0
    if meta_expires_at ~= false then
        replaced_stale = 1
    end
    return {replaced_stale, version, lock_expires_at, now + data_cache_time}
end

local existing_uid = redis.call('HGET', meta_key, 'uid')
local initialized_at = tonumber(redis.call('HGET', meta_key, 'initialized_at'))

redis.call('SET', writer_lock_key, lock_uid_if_acquired)
redis.call('EXPIREAT', writer_lock_key, lock_expires_at)
redis.call(
    'PUBLISH',
    'ps:client_flow_graph_analysis:lock_changed',
    struct.pack('>I4', string.len(graph_id)) 
        .. graph_id 
        .. struct.pack('>I2', 0)
        .. struct.pack('>I1', 1)
)

return {2, existing_uid, version, lock_expires_at, initialized_at, meta_expires_at}
"""

CLIENT_FLOW_GRAPH_ANALYSIS_ACQUIRE_WRITE_LOCK_LUA_SCRIPT_HASH = hashlib.sha1(
    CLIENT_FLOW_GRAPH_ANALYSIS_ACQUIRE_WRITE_LOCK_LUA_SCRIPT.encode("utf-8")
).hexdigest()


_last_client_flow_graph_analysis_acquire_write_lock_ensured_at: Optional[float] = None


async def ensure_client_flow_graph_analysis_acquire_write_lock_script_exists(
    redis: redis.asyncio.client.Redis, *, force: bool = False
) -> None:
    """Ensures the client_flow_graph_analysis_acquire_write_lock lua script is loaded into redis."""
    global _last_client_flow_graph_analysis_acquire_write_lock_ensured_at

    now = time.time()
    if (
        not force
        and _last_client_flow_graph_analysis_acquire_write_lock_ensured_at is not None
        and (now - _last_client_flow_graph_analysis_acquire_write_lock_ensured_at < 5)
    ):
        return

    loaded: List[bool] = await redis.script_exists(
        CLIENT_FLOW_GRAPH_ANALYSIS_ACQUIRE_WRITE_LOCK_LUA_SCRIPT_HASH
    )
    if not loaded[0]:
        correct_hash = await redis.script_load(
            CLIENT_FLOW_GRAPH_ANALYSIS_ACQUIRE_WRITE_LOCK_LUA_SCRIPT
        )
        assert (
            correct_hash
            == CLIENT_FLOW_GRAPH_ANALYSIS_ACQUIRE_WRITE_LOCK_LUA_SCRIPT_HASH
        ), f"{correct_hash=} != {CLIENT_FLOW_GRAPH_ANALYSIS_ACQUIRE_WRITE_LOCK_LUA_SCRIPT_HASH=}"

    if (
        _last_client_flow_graph_analysis_acquire_write_lock_ensured_at is None
        or _last_client_flow_graph_analysis_acquire_write_lock_ensured_at < now
    ):
        _last_client_flow_graph_analysis_acquire_write_lock_ensured_at = now


@dataclass
class ClientFlowGraphAnalysisAcquireWriteLockResultInitialized:
    type: Literal["initialized"]
    """Indicates we initialized the meta tag as it did not exist"""
    version: int
    """The value of `client_flow_graph_analysis:version` when this lock was acquired"""
    stale_at: int
    """The time at which your lock will expire in seconds since the epoch"""
    expires_at: int
    """The time at which the meta key will expire in seconds since the epoch"""


@dataclass
class ClientFlowGraphAnalysisAcquireWriteLockResultReplacedStale:
    type: Literal["replaced_stale"]
    """Indicates that the meta tag existed but was about to expire and was write-lockable,
    so we replaced the data uid while acquiring the writer lock
    """
    version: int
    """The value of `client_flow_graph_analysis:version` when this lock was acquired"""
    stale_at: int
    """The time at which your lock will expire in seconds since the epoch"""
    expires_at: int
    """The time at which the meta key will expire in seconds since the epoch"""


@dataclass
class ClientFlowGraphAnalysisAcquireWriteLockResultExistingSuccess:
    type: Literal["existing_success"]
    """Indicates that the meta tag existed but had no readers or writers, thus we acquired the writer lock"""
    data_uid: bytes
    """The unique identifier for where data can be accessed"""
    version: int
    """The value of `client_flow_graph_analysis:version` when this lock was acquired"""
    stale_at: int
    """When the acquired lock will expire in seconds since the epoch"""
    initialized_at: int
    """When the meta key was initialized in seconds since the epoch"""
    expires_at: int
    """When the meta key will expire in seconds since the epoch"""


@dataclass
class ClientFlowGraphAnalysisAcquireWriteLockResultExistingLocked:
    type: Literal["existing_locked"]
    """Indicates that the meta tag existed and was locked by a writer or reader"""
    version: int
    """The value of `client_flow_graph_analysis:version` when we failed to get this lock"""
    readers: int
    """How many reader locks are currently held"""
    writer: bool
    """Whether a writer lock is currently held"""


ClientFlowGraphAnalysisAcquireWriteLockResult = Union[
    ClientFlowGraphAnalysisAcquireWriteLockResultInitialized,
    ClientFlowGraphAnalysisAcquireWriteLockResultReplacedStale,
    ClientFlowGraphAnalysisAcquireWriteLockResultExistingSuccess,
    ClientFlowGraphAnalysisAcquireWriteLockResultExistingLocked,
]


async def client_flow_graph_analysis_acquire_write_lock(
    redis: redis.asyncio.client.Redis,
    graph_id: bytes,
    uid_if_initialize: bytes,
    lock_uid_if_acquired: bytes,
    now: int,
    min_ttl: int,
) -> Optional[ClientFlowGraphAnalysisAcquireWriteLockResult]:
    """

    Args:
        redis (redis.asyncio.client.Redis): The redis client
        graph_id (bytes): The unique identifier for the settings used to produce the graph
        uid_if_initialize (bytes): The uid to use for the data if the meta tag is initialized
            or replaced
        lock_uid_if_acquired (bytes): The uid to use for write lock
        now (int): The current time in seconds since the epoch
        min_ttl (int): Expressed in seconds, if the graph meta tag exists but is going to expire
            within this period of time (in seconds), it will be replaced with a new data uid


    Returns:
        Optional[ClientFlowGraphAnalysisAcquireWriteLockResult]: The result of the lock acquisition,
            unless run within a pipeline, in which case the result is not known until the pipeline
            is executed

    Raises:
        NoScriptError: If the script is not loaded into redis
    """
    res = await redis.evalsha(
        CLIENT_FLOW_GRAPH_ANALYSIS_ACQUIRE_WRITE_LOCK_LUA_SCRIPT_HASH,  # type: ignore
        0,  # type: ignore
        graph_id,  # type: ignore
        uid_if_initialize,  # type: ignore
        lock_uid_if_acquired,  # type: ignore
        now,  # type: ignore
        min_ttl,  # type: ignore
    )
    if res is redis:
        return None
    return parse_client_flow_graph_analysis_acquire_write_lock(res)


async def safe_client_flow_graph_analysis_acquire_write_lock(
    itgs: Itgs,
    /,
    *,
    graph_id: bytes,
    uid_if_initialize: bytes,
    lock_uid_if_acquired: bytes,
    now: int,
    min_ttl: int,
) -> ClientFlowGraphAnalysisAcquireWriteLockResult:
    """Same as client_flow_graph_analysis_acquire_write_lock but executes in the
    primary redis instance (and thus not a pipeline), so the result is known
    """
    redis = await itgs.redis()

    async def _prepare(force: bool):
        await ensure_client_flow_graph_analysis_acquire_write_lock_script_exists(
            redis, force=force
        )

    async def _execute():
        return await client_flow_graph_analysis_acquire_write_lock(
            redis,
            graph_id,
            uid_if_initialize,
            lock_uid_if_acquired,
            now,
            min_ttl,
        )

    result = await run_with_prep(_prepare, _execute)
    assert result is not None
    return result


def parse_client_flow_graph_analysis_acquire_write_lock(
    res: Any,
) -> ClientFlowGraphAnalysisAcquireWriteLockResult:
    """Parses the result of the write lock script into the preferred form"""
    assert isinstance(res, (list, tuple)), res
    assert len(res) >= 1, res

    type = int(res[0])
    if type == 0:
        assert len(res) == 4, res
        return ClientFlowGraphAnalysisAcquireWriteLockResultInitialized(
            type="initialized",
            version=int(res[1]),
            stale_at=int(res[2]),
            expires_at=int(res[3]),
        )
    if type == 1:
        assert len(res) == 4, res
        return ClientFlowGraphAnalysisAcquireWriteLockResultReplacedStale(
            type="replaced_stale",
            version=int(res[1]),
            stale_at=int(res[2]),
            expires_at=int(res[3]),
        )
    if type == 2:
        assert len(res) == 6, res
        return ClientFlowGraphAnalysisAcquireWriteLockResultExistingSuccess(
            type="existing_success",
            data_uid=res[1],
            version=int(res[2]),
            stale_at=int(res[3]),
            initialized_at=int(res[4]),
            expires_at=int(res[5]),
        )
    if type == 3:
        assert len(res) == 4, res
        return ClientFlowGraphAnalysisAcquireWriteLockResultExistingLocked(
            type="existing_locked",
            version=int(res[1]),
            readers=int(res[2]),
            writer=bool(res[3]),
        )
    assert False, res
