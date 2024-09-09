from dataclasses import dataclass
from typing import Any, Literal, Optional, List, Union
import hashlib
import time
import redis.asyncio.client

from itgs import Itgs
from redis_helpers.run_with_prep import run_with_prep

CLIENT_FLOW_GRAPH_ANALYSIS_ACQUIRE_READ_LOCK_LUA_SCRIPT = """
local graph_id = ARGV[1]
local lock_uid_if_acquired = ARGV[2]
local now = tonumber(ARGV[3])
local min_ttl = tonumber(ARGV[4])

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
if writers > 0 then
    return {3, version, readers, writers}
end

local meta_key = key_base .. ':meta'

local meta_expires_at_str = redis.call('HGET', meta_key, 'expires_at')
local meta_expires_at = false
if meta_expires_at_str ~= false then
    meta_expires_at = tonumber(meta_expires_at_str)
end

if meta_expires_at == false or meta_expires_at - now < min_ttl then
    local return_type = 1
    if meta_expires_at ~= false then
        return_type = 2
    end
    return {return_type, version}
end

local existing_uid = redis.call('HGET', meta_key, 'uid')
local initialized_at = tonumber(redis.call('HGET', meta_key, 'initialized_at'))

redis.call('ZADD', readers_lock_key, now + lock_time, lock_uid_if_acquired)
redis.call('EXPIREAT', readers_lock_key, now + lock_time, 'NX')
redis.call('EXPIREAT', readers_lock_key, now + lock_time, 'GT')
redis.call(
    'PUBLISH',
    'ps:client_flow_graph_analysis:lock_changed',
    struct.pack('>I4', string.len(graph_id)) 
        .. graph_id 
        .. struct.pack('>I2', readers + 1)
        .. struct.pack('>I1', 0)
)

return {0, existing_uid, version, now + lock_time, initialized_at, meta_expires_at}
"""

CLIENT_FLOW_GRAPH_ANALYSIS_ACQUIRE_READ_LOCK_LUA_SCRIPT_HASH = hashlib.sha1(
    CLIENT_FLOW_GRAPH_ANALYSIS_ACQUIRE_READ_LOCK_LUA_SCRIPT.encode("utf-8")
).hexdigest()


_last_client_flow_graph_analysis_acquire_read_lock_ensured_at: Optional[float] = None


async def ensure_client_flow_graph_analysis_acquire_read_lock_script_exists(
    redis: redis.asyncio.client.Redis, *, force: bool = False
) -> None:
    """Ensures the client_flow_graph_analysis_acquire_read_lock lua script is loaded into redis."""
    global _last_client_flow_graph_analysis_acquire_read_lock_ensured_at

    now = time.time()
    if (
        not force
        and _last_client_flow_graph_analysis_acquire_read_lock_ensured_at is not None
        and (now - _last_client_flow_graph_analysis_acquire_read_lock_ensured_at < 5)
    ):
        return

    loaded: List[bool] = await redis.script_exists(
        CLIENT_FLOW_GRAPH_ANALYSIS_ACQUIRE_READ_LOCK_LUA_SCRIPT_HASH
    )
    if not loaded[0]:
        correct_hash = await redis.script_load(
            CLIENT_FLOW_GRAPH_ANALYSIS_ACQUIRE_READ_LOCK_LUA_SCRIPT
        )
        assert (
            correct_hash == CLIENT_FLOW_GRAPH_ANALYSIS_ACQUIRE_READ_LOCK_LUA_SCRIPT_HASH
        ), f"{correct_hash=} != {CLIENT_FLOW_GRAPH_ANALYSIS_ACQUIRE_READ_LOCK_LUA_SCRIPT_HASH=}"

    if (
        _last_client_flow_graph_analysis_acquire_read_lock_ensured_at is None
        or _last_client_flow_graph_analysis_acquire_read_lock_ensured_at < now
    ):
        _last_client_flow_graph_analysis_acquire_read_lock_ensured_at = now


@dataclass
class ClientFlowGraphAnalysisAcquireReadLockResultNotFound:
    type: Literal["not_found"]
    """Indicates we could not acquire a reader lock as there was nothing to read"""
    version: int
    """The value of `client_flow_graph_analysis:version` when we failed to get this lock"""


@dataclass
class ClientFlowGraphAnalysisAcquireReadLockResultStale:
    type: Literal["stale"]
    """Indicates we could not acquire a reader lock as the value there is too stale"""
    version: int
    """The value of `client_flow_graph_analysis:version` when we failed to get this lock"""


@dataclass
class ClientFlowGraphAnalysisAcquireReadLockResultExistingSuccess:
    type: Literal["existing_success"]
    """Indicates that the meta tag existed and had no writers, thus we acquired the reader lock"""
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
class ClientFlowGraphAnalysisAcquireReadLockResultExistingLocked:
    type: Literal["existing_locked"]
    """Indicates that the meta tag existed and was locked by a writer or reader"""
    version: int
    """The value of `client_flow_graph_analysis:version` when we failed to get this lock"""
    readers: int
    """How many reader locks are currently held"""
    writer: bool
    """Whether a writer lock is currently held"""


ClientFlowGraphAnalysisAcquireReadLockResult = Union[
    ClientFlowGraphAnalysisAcquireReadLockResultNotFound,
    ClientFlowGraphAnalysisAcquireReadLockResultStale,
    ClientFlowGraphAnalysisAcquireReadLockResultExistingSuccess,
    ClientFlowGraphAnalysisAcquireReadLockResultExistingLocked,
]


async def client_flow_graph_analysis_acquire_read_lock(
    redis: redis.asyncio.client.Redis,
    graph_id: bytes,
    lock_uid_if_acquired: bytes,
    now: int,
    min_ttl: int,
) -> Optional[ClientFlowGraphAnalysisAcquireReadLockResult]:
    """

    Args:
        redis (redis.asyncio.client.Redis): The redis client
        graph_id (bytes): The unique identifier for the settings used to produce the graph
        lock_uid_if_acquired (bytes): The uid to use for read lock
        now (int): The current time in seconds since the epoch
        min_ttl (int): Expressed in seconds, if the graph meta tag exists but is going to expire
            within this period of time (in seconds), it will be replaced with a new data uid


    Returns:
        Optional[ClientFlowGraphAnalysisAcquireReadLockResult]: The result of the lock acquisition,
            unless run within a pipeline, in which case the result is not known until the pipeline
            is executed

    Raises:
        NoScriptError: If the script is not loaded into redis
    """
    res = await redis.evalsha(
        CLIENT_FLOW_GRAPH_ANALYSIS_ACQUIRE_READ_LOCK_LUA_SCRIPT_HASH,  # type: ignore
        0,  # type: ignore
        graph_id,  # type: ignore
        lock_uid_if_acquired,  # type: ignore
        now,  # type: ignore
        min_ttl,  # type: ignore
    )
    if res is redis:
        return None
    return parse_client_flow_graph_analysis_acquire_read_lock(res)


async def safe_client_flow_graph_analysis_acquire_read_lock(
    itgs: Itgs,
    /,
    *,
    graph_id: bytes,
    lock_uid_if_acquired: bytes,
    now: int,
    min_ttl: int,
) -> ClientFlowGraphAnalysisAcquireReadLockResult:
    """Same as client_flow_graph_analysis_acquire_read_lock but executes in the
    primary redis instance (and thus not a pipeline), so the result is known
    """
    redis = await itgs.redis()

    async def _prepare(force: bool):
        await ensure_client_flow_graph_analysis_acquire_read_lock_script_exists(
            redis, force=force
        )

    async def _execute():
        return await client_flow_graph_analysis_acquire_read_lock(
            redis,
            graph_id,
            lock_uid_if_acquired,
            now,
            min_ttl,
        )

    result = await run_with_prep(_prepare, _execute)
    assert result is not None
    return result


def parse_client_flow_graph_analysis_acquire_read_lock(
    res: Any,
) -> ClientFlowGraphAnalysisAcquireReadLockResult:
    """Parses the result of the read lock script into the preferred form"""
    assert isinstance(res, (list, tuple)), res
    assert len(res) >= 1, res

    type = int(res[0])
    if type == 0:
        assert len(res) == 6, res
        return ClientFlowGraphAnalysisAcquireReadLockResultExistingSuccess(
            type="existing_success",
            data_uid=res[1],
            version=int(res[2]),
            stale_at=int(res[3]),
            initialized_at=int(res[4]),
            expires_at=int(res[5]),
        )
    if type == 1:
        assert len(res) == 2, res
        return ClientFlowGraphAnalysisAcquireReadLockResultNotFound(
            type="not_found",
            version=int(res[1]),
        )
    if type == 2:
        assert len(res) == 2, res
        return ClientFlowGraphAnalysisAcquireReadLockResultStale(
            type="stale",
            version=int(res[1]),
        )
    if type == 3:
        assert len(res) == 4, res
        return ClientFlowGraphAnalysisAcquireReadLockResultExistingLocked(
            type="existing_locked",
            version=int(res[1]),
            readers=int(res[2]),
            writer=bool(res[3]),
        )
    assert False, res
