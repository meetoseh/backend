from typing import Any, Literal, Optional, List, Union, cast
import hashlib
import time
import redis.asyncio.client
from dataclasses import dataclass

from itgs import Itgs
from redis_helpers.run_with_prep import run_with_prep

CLIENT_FLOW_GRAPH_ANALYSIS_READ_PATHS_PAGE_LUA_SCRIPT = """
local graph_id = ARGV[1]
local version_str = ARGV[2]
local is_writer_lock = ARGV[3] == "1"
local lock_uid = ARGV[4]
local source = ARGV[5]
local target = ARGV[6]
local inverted = ARGV[7] == "1"
local max_steps_str = ARGV[8]
local offset_str = ARGV[9]
local limit_str = ARGV[10]
local now_str = ARGV[11]

local base_key_meta =
    "client_flow_graph_analysis:" 
    .. graph_id
    .. ':'
    .. version_str

if is_writer_lock then
    local writer_lock_key = base_key_meta .. ":writer"
    local current_writer_lock_uid = redis.call("GET", writer_lock_key)
    if current_writer_lock_uid ~= lock_uid then
        return {-1}
    end
else
    local readers_lock_key = base_key_meta .. ":readers"
    redis.call("ZREMRANGEBYSCORE", readers_lock_key, "-inf", now_str)
    local current_score = redis.call("ZSCORE", readers_lock_key, lock_uid)
    if current_score == false then
        return {-1}
    end
end

local meta_key = base_key_meta .. ':meta'
local data_uid = redis.call("HGET", meta_key, "uid")
if data_uid == false then
    return {-4}
end

local reachable_key =
    "client_flow_graph_analysis:" 
    .. data_uid
    .. (inverted and ":inverted_reachable:" or ":reachable:")
    .. source
    .. (max_steps_str ~= "0" and (":" .. max_steps_str) or "")

local reachable_is_usable = redis.call('SISMEMBER', reachable_key, '__computed__')
if reachable_is_usable ~= 1 then
    return {-3}
end

local paths_key = reachable_key .. ':paths:' .. target
local last_item = redis.call('LINDEX', paths_key, -1)
if last_item == false then
    return {-2}
end
if last_item ~= '{"type":"done"}' then
    return {-4}
end

local offset = tonumber(offset_str)
local limit = tonumber(limit_str)
local page = redis.call('LRANGE', paths_key, offset, offset + limit - 1)
return {1, page}
"""

CLIENT_FLOW_GRAPH_ANALYSIS_READ_PATHS_PAGE_LUA_SCRIPT_HASH = hashlib.sha1(
    CLIENT_FLOW_GRAPH_ANALYSIS_READ_PATHS_PAGE_LUA_SCRIPT.encode("utf-8")
).hexdigest()


_last_client_flow_graph_analysis_read_paths_page_ensured_at: Optional[float] = None


async def ensure_client_flow_graph_analysis_read_paths_page_script_exists(
    redis: redis.asyncio.client.Redis, *, force: bool = False
) -> None:
    """Ensures the client_flow_graph_analysis_read_paths_page lua script is loaded into redis."""
    global _last_client_flow_graph_analysis_read_paths_page_ensured_at

    now = time.time()
    if (
        not force
        and _last_client_flow_graph_analysis_read_paths_page_ensured_at is not None
        and (now - _last_client_flow_graph_analysis_read_paths_page_ensured_at < 5)
    ):
        return

    loaded: List[bool] = await redis.script_exists(
        CLIENT_FLOW_GRAPH_ANALYSIS_READ_PATHS_PAGE_LUA_SCRIPT_HASH
    )
    if not loaded[0]:
        correct_hash = await redis.script_load(
            CLIENT_FLOW_GRAPH_ANALYSIS_READ_PATHS_PAGE_LUA_SCRIPT
        )
        assert (
            correct_hash == CLIENT_FLOW_GRAPH_ANALYSIS_READ_PATHS_PAGE_LUA_SCRIPT_HASH
        ), f"{correct_hash=} != {CLIENT_FLOW_GRAPH_ANALYSIS_READ_PATHS_PAGE_LUA_SCRIPT_HASH=}"

    if (
        _last_client_flow_graph_analysis_read_paths_page_ensured_at is None
        or _last_client_flow_graph_analysis_read_paths_page_ensured_at < now
    ):
        _last_client_flow_graph_analysis_read_paths_page_ensured_at = now


@dataclass
class ClientFlowGraphAnalysisReadPathsPageResultSuccess:
    type: Literal["success"]
    """
    - `success`: the page was read successfully
    """
    page: List[bytes]
    """The paths in the page, each decodable as lib.client_flows.analysis.FlowPathOrDone"""


@dataclass
class ClientFlowGraphAnalysisReadPathsPageResultLockLost:
    type: Literal["lock_lost"]
    """
    - `lock_lost`: you no longer hold the indicated lock
    """


@dataclass
class ClientFlowGraphAnalysisReadPathsPageResultNoPaths:
    type: Literal["no_paths"]
    """
    - `no_paths`: the analysis required for this question is in the cache,
        and it indicates that there are no matching paths
    """


@dataclass
class ClientFlowGraphAnalysisReadPathsPageResultNotFound:
    type: Literal["not_found"]
    """
    - `not_found`: the analysis required to answer this question is not in the cache
    """


@dataclass
class ClientFlowGraphAnalysisReadPathsPageResultCorrupted:
    type: Literal["corrupted"]
    """
    - `corrupted`: we detected an invariant did not hold
    """


ClientFlowGraphAnalysisReadPathsPageResult = Union[
    ClientFlowGraphAnalysisReadPathsPageResultSuccess,
    ClientFlowGraphAnalysisReadPathsPageResultLockLost,
    ClientFlowGraphAnalysisReadPathsPageResultNoPaths,
    ClientFlowGraphAnalysisReadPathsPageResultNotFound,
    ClientFlowGraphAnalysisReadPathsPageResultCorrupted,
]


async def client_flow_graph_analysis_read_paths_page(
    redis: redis.asyncio.client.Redis,
    /,
    *,
    graph_id: bytes,
    version: int,
    lock_type: Literal["reader", "writer"],
    lock_uid: bytes,
    source: bytes,
    target: bytes,
    inverted: bool,
    max_steps: Optional[int],
    offset: int,
    limit: int,
    now: int,
) -> Optional[ClientFlowGraphAnalysisReadPathsPageResult]:
    """
    Args:
        redis (redis.asyncio.client.Redis): The redis client
        graph_id (bytes): the identifier for the environment settings used to
            produce the graph; see lib.client_flows.analysis.ClientFlowAnalysisEnvironment
        version (int): the value of `client_flow_graph_analysis:version` when the lock was
            acquired
        lock_type ("reader" | "writer"): the type of lock you hold
        lock_uid (bytes): the unique identifier of the lock you hold
        source (bytes): the source flow slug of the paths. will be omitted from the
            returned paths
        target (bytes): the target flow slug of the paths
        inverted (bool): True to look at the inverted graph (thus giving target -> source),
            False to look at the normal graph (thus giving source -> target)
        max_steps (int, None): when the paths were generated, how many steps from the source
            were considered
        offset (int): how many paths to skip from the beginning
        limit (int): the maximum number of paths to return
        now (int): current time in seconds since the epoch

    Returns:
        ClientFlowGraphAnalysisReadPathsPageResult, None: The result. None if executed
            within a transaction, since the result is not known until the
            transaction is executed.

    Raises:
        NoScriptError: If the script is not loaded into redis
    """
    res = await redis.evalsha(
        CLIENT_FLOW_GRAPH_ANALYSIS_READ_PATHS_PAGE_LUA_SCRIPT_HASH,
        0,
        graph_id,  # type: ignore
        str(version).encode("ascii"),  # type: ignore
        b"1" if lock_type == "writer" else b"0",  # type: ignore
        lock_uid,  # type: ignore
        source,  # type: ignore
        target,  # type: ignore
        b"1" if inverted else b"0",  # type: ignore
        b"0" if max_steps is None else str(max_steps).encode("ascii"),  # type: ignore
        str(offset).encode("ascii"),  # type: ignore
        str(limit).encode("ascii"),  # type: ignore
        str(now).encode("ascii"),  # type: ignore
    )
    if res is redis:
        return None
    return parse_client_flow_graph_analysis_read_paths_page_result(res)


async def safe_client_flow_graph_analysis_read_paths_page(
    itgs: Itgs,
    /,
    *,
    graph_id: bytes,
    version: int,
    lock_type: Literal["reader", "writer"],
    lock_uid: bytes,
    source: bytes,
    target: bytes,
    inverted: bool,
    max_steps: Optional[int],
    offset: int,
    limit: int,
    now: int,
) -> ClientFlowGraphAnalysisReadPathsPageResult:
    """Same as client_flow_graph_analysis_read_paths_page, but always runs in the
    standard redis instance of the given itgs and thus doesn't need an optional
    return value
    """
    redis = await itgs.redis()

    async def prepare(force: bool):
        await ensure_client_flow_graph_analysis_read_paths_page_script_exists(
            redis, force=force
        )

    async def execute():
        return await client_flow_graph_analysis_read_paths_page(
            redis,
            graph_id=graph_id,
            version=version,
            lock_type=lock_type,
            lock_uid=lock_uid,
            source=source,
            target=target,
            inverted=inverted,
            max_steps=max_steps,
            offset=offset,
            limit=limit,
            now=now,
        )

    res = await run_with_prep(prepare, execute)
    assert res is not None
    return res


def parse_client_flow_graph_analysis_read_paths_page_result(
    raw: Any,
) -> ClientFlowGraphAnalysisReadPathsPageResult:
    """Parses the response from redis to the journal chat jobs start lua script
    into a more interpretable value
    """
    assert isinstance(raw, (list, tuple)), raw
    assert len(raw) > 0, raw
    type_ = int(raw[0])

    if type_ == -1:
        return ClientFlowGraphAnalysisReadPathsPageResultLockLost(type="lock_lost")
    elif type_ == -2:
        return ClientFlowGraphAnalysisReadPathsPageResultNoPaths(type="no_paths")
    elif type_ == -3:
        return ClientFlowGraphAnalysisReadPathsPageResultNotFound(type="not_found")
    elif type_ == -4:
        return ClientFlowGraphAnalysisReadPathsPageResultCorrupted(type="corrupted")
    elif type_ == 1:
        assert len(raw) == 2, raw
        assert isinstance(raw[1], (list, tuple)), raw
        return ClientFlowGraphAnalysisReadPathsPageResultSuccess(
            type="success", page=cast(list, raw[1])
        )

    raise ValueError(f"bad return value: {raw}")
