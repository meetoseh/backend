from typing import Any, Literal, Optional, List, Union
import hashlib
import time
import redis.asyncio.client
from dataclasses import dataclass

from itgs import Itgs
from redis_helpers.run_with_prep import run_with_prep

CLIENT_FLOW_GRAPH_ANALYSIS_RELEASE_WRITE_LOCK_LUA_SCRIPT = """
local graph_id = ARGV[1]
local version_str = ARGV[2]
local lock_uid = ARGV[3]

local key_base = 'client_flow_graph_analysis:' .. graph_id .. ':' .. version_str
local writer_lock_key = key_base .. ':writer'

local current_writer = redis.call('GET', writer_lock_key)
if current_writer ~= lock_uid then
    return -1
end

redis.call('DEL', writer_lock_key)
redis.call(
    'PUBLISH',
    'ps:client_flow_graph_analysis:lock_changed',
    struct.pack('>I4', string.len(graph_id)) 
        .. graph_id 
        .. struct.pack('>I2', 0)
        .. struct.pack('>I1', 0)
)
return 1
"""

CLIENT_FLOW_GRAPH_ANALYSIS_RELEASE_WRITE_LOCK_LUA_SCRIPT_HASH = hashlib.sha1(
    CLIENT_FLOW_GRAPH_ANALYSIS_RELEASE_WRITE_LOCK_LUA_SCRIPT.encode("utf-8")
).hexdigest()


_last_client_flow_graph_analysis_release_write_lock_ensured_at: Optional[float] = None


async def ensure_client_flow_graph_analysis_release_write_lock_script_exists(
    redis: redis.asyncio.client.Redis, *, force: bool = False
) -> None:
    """Ensures the client_flow_graph_analysis_release_write_lock lua script is loaded into redis."""
    global _last_client_flow_graph_analysis_release_write_lock_ensured_at

    now = time.time()
    if (
        not force
        and _last_client_flow_graph_analysis_release_write_lock_ensured_at is not None
        and (now - _last_client_flow_graph_analysis_release_write_lock_ensured_at < 5)
    ):
        return

    loaded: List[bool] = await redis.script_exists(
        CLIENT_FLOW_GRAPH_ANALYSIS_RELEASE_WRITE_LOCK_LUA_SCRIPT_HASH
    )
    if not loaded[0]:
        correct_hash = await redis.script_load(
            CLIENT_FLOW_GRAPH_ANALYSIS_RELEASE_WRITE_LOCK_LUA_SCRIPT
        )
        assert (
            correct_hash
            == CLIENT_FLOW_GRAPH_ANALYSIS_RELEASE_WRITE_LOCK_LUA_SCRIPT_HASH
        ), f"{correct_hash=} != {CLIENT_FLOW_GRAPH_ANALYSIS_RELEASE_WRITE_LOCK_LUA_SCRIPT_HASH=}"

    if (
        _last_client_flow_graph_analysis_release_write_lock_ensured_at is None
        or _last_client_flow_graph_analysis_release_write_lock_ensured_at < now
    ):
        _last_client_flow_graph_analysis_release_write_lock_ensured_at = now


@dataclass
class ClientFlowGraphAnalysisReleaseWriteLockResultSuccess:
    type: Literal["success"]
    """
    - `success`: you still held the write lock and it was released
    """


@dataclass
class ClientFlowGraphAnalysisReleaseWriteLockResultLockLost:
    type: Literal["lock_lost"]
    """
    - `lock_lost`: you no longer held the write lock
    """


ClientFlowGraphAnalysisReleaseWriteLockResult = Union[
    ClientFlowGraphAnalysisReleaseWriteLockResultSuccess,
    ClientFlowGraphAnalysisReleaseWriteLockResultLockLost,
]


async def client_flow_graph_analysis_release_write_lock(
    redis: redis.asyncio.client.Redis, graph_id: bytes, version: int, lock_uid: bytes
) -> Optional[ClientFlowGraphAnalysisReleaseWriteLockResult]:
    """Releases the write lock on the graph identified by the given id acquired
    when the global version counter (`client_flow_graph_analysis:version`) was
    `version` if it is still held (as identified by the lock uid `lock_uid`)

    Args:
        redis (redis.asyncio.client.Redis): The redis client
        graph_id (bytes): The id of the graph
        version (int): The version at the time the lock was acquired
        lock_uid (bytes): The lock uid that you used

    Returns:
        ClientFlowGraphAnalysisReleaseWriteLockResult, None: The result. None if
            executed within a transaction, since the result is not known until
            the transaction is executed.

    Raises:
        NoScriptError: If the script is not loaded into redis
    """
    res = await redis.evalsha(
        CLIENT_FLOW_GRAPH_ANALYSIS_RELEASE_WRITE_LOCK_LUA_SCRIPT_HASH,
        0,
        graph_id,  # type: ignore
        version,  # type: ignore
        lock_uid,  # type: ignore
    )
    if res is redis:
        return None
    return parse_client_flow_graph_analysis_release_write_lock_result(res)


async def safe_client_flow_graph_analysis_release_write_lock(
    itgs: Itgs,
    /,
    *,
    graph_id: bytes,
    version: int,
    lock_uid: bytes,
) -> ClientFlowGraphAnalysisReleaseWriteLockResult:
    """Same as `client_flow_graph_analysis_release_write_lock`, but uses the standard
    redis instance (and thus definitely not a pipeline) and thus can guarrantee a result
    and handle loading the script if necessary

    Args:
        itgs (Itgs): the integrations to (re)use
        graph_id (bytes): The id of the graph
        version (int): The version at the time the lock was acquired
        lock_uid (bytes): The lock uid that you used
    """
    redis = await itgs.redis()

    async def _prepare(force: bool):
        await ensure_client_flow_graph_analysis_release_write_lock_script_exists(
            redis, force=force
        )

    async def _execute():
        return await client_flow_graph_analysis_release_write_lock(
            redis, graph_id, version, lock_uid
        )

    result = await run_with_prep(_prepare, _execute)
    assert result is not None
    return result


def parse_client_flow_graph_analysis_release_write_lock_result(
    res: Any,
) -> ClientFlowGraphAnalysisReleaseWriteLockResult:
    assert isinstance(res, int), res
    if res == 1:
        return ClientFlowGraphAnalysisReleaseWriteLockResultSuccess("success")
    if res == -1:
        return ClientFlowGraphAnalysisReleaseWriteLockResultLockLost("lock_lost")
    raise ValueError(f"Unknown result: {res}")