from typing import Any, Literal, Optional, List, Union
import hashlib
import time
import redis.asyncio.client
from dataclasses import dataclass

from itgs import Itgs
from redis_helpers.run_with_prep import run_with_prep

CLIENT_FLOW_GRAPH_ANALYSIS_READ_REACHABLE_LUA_SCRIPT = """
local graph_id = ARGV[1]
local version_str = ARGV[2]
local is_writer_lock = ARGV[3] == '1'
local lock_uid = ARGV[4]
local source_flow_slug = ARGV[5]
local inverted = ARGV[6] == '1'
local now_str = ARGV[7]
local cursor_str = ARGV[8]
local max_steps_str = ARGV[9]

if max_steps_str == nil then
    max_steps_str = false
end

local base_key_meta = 'client_flow_graph_analysis:' .. graph_id .. ':' .. version_str

if is_writer_lock then
    local writer_lock_key = base_key_meta .. ':writer'
    local current_lock_uid = redis.call('GET', writer_lock_key)
    if current_lock_uid ~= lock_uid then
        return {-1}
    end
else
    local readers_lock_key = base_key_meta .. ':readers'
    local now = tonumber(now_str)
    redis.call('ZREMRANGEBYSCORE', readers_lock_key, '-inf', now)

    local current_score = redis.call('ZSCORE', readers_lock_key, lock_uid)
    if current_score == false then
        return {-1}
    end
end

local meta_key = base_key_meta .. ':meta'
local data_uid = redis.call('HGET', meta_key, 'uid')
if data_uid == false then
    return {-3}
end

local reachable_key = 
    'client_flow_graph_analysis:' 
    .. data_uid 
    .. ':' 
    .. (inverted and 'inverted_' or '') 
    .. 'reachable:'
    .. source_flow_slug
    .. (max_steps_str ~= false and (':' .. max_steps_str) or '')

local reachable_usable = redis.call('SISMEMBER', reachable_key, '__computed__')
if reachable_usable ~= 1 then
    return {-2}
end

local scan_result = redis.call('SSCAN', reachable_key, cursor_str)
local new_cursor = scan_result[1]
local scanned_reachable = scan_result[2]

local reachable_list = {}
for _, item in ipairs(scanned_reachable) do
    if item ~= '__computed__' then
        local item_key = reachable_key .. ':paths:' .. item
        local last_item = redis.call('LINDEX', item_key, -1)
        if last_item ~= '{"type":"done"}' then
            return {-3}
        end

        local first_item = redis.call('LINDEX', item_key, 0)
        table.insert(reachable_list, {item, redis.call('LLEN', item_key) - 1, first_item})
    end
end

return {1, reachable_list, new_cursor}
"""

CLIENT_FLOW_GRAPH_ANALYSIS_READ_REACHABLE_LUA_SCRIPT_HASH = hashlib.sha1(
    CLIENT_FLOW_GRAPH_ANALYSIS_READ_REACHABLE_LUA_SCRIPT.encode("utf-8")
).hexdigest()


_last_client_flow_graph_analysis_read_reachable_ensured_at: Optional[float] = None


async def ensure_client_flow_graph_analysis_read_reachable_script_exists(
    redis: redis.asyncio.client.Redis, *, force: bool = False
) -> None:
    """Ensures the client_flow_graph_analysis_read_reachable lua script is loaded into redis."""
    global _last_client_flow_graph_analysis_read_reachable_ensured_at

    now = time.time()
    if (
        not force
        and _last_client_flow_graph_analysis_read_reachable_ensured_at is not None
        and (now - _last_client_flow_graph_analysis_read_reachable_ensured_at < 5)
    ):
        return

    loaded: List[bool] = await redis.script_exists(
        CLIENT_FLOW_GRAPH_ANALYSIS_READ_REACHABLE_LUA_SCRIPT_HASH
    )
    if not loaded[0]:
        correct_hash = await redis.script_load(
            CLIENT_FLOW_GRAPH_ANALYSIS_READ_REACHABLE_LUA_SCRIPT
        )
        assert (
            correct_hash == CLIENT_FLOW_GRAPH_ANALYSIS_READ_REACHABLE_LUA_SCRIPT_HASH
        ), f"{correct_hash=} != {CLIENT_FLOW_GRAPH_ANALYSIS_READ_REACHABLE_LUA_SCRIPT_HASH=}"

    if (
        _last_client_flow_graph_analysis_read_reachable_ensured_at is None
        or _last_client_flow_graph_analysis_read_reachable_ensured_at < now
    ):
        _last_client_flow_graph_analysis_read_reachable_ensured_at = now


@dataclass
class ClientFlowGraphAnalysisReadReachableItem:
    slug: bytes
    """The slug of the flow reachable from the source"""
    count: int
    """The number of paths from the source to this flow"""
    first: bytes
    """
    An example path from the source to this flow; you can parse this with lib.client_flows.analysis
    if you need it in a usable format.
    """


@dataclass
class ClientFlowGraphAnalysisReadReachableResultSuccess:
    type: Literal["success"]
    """
    - `success`: reachable values found
    """
    flow_items: List[ClientFlowGraphAnalysisReadReachableItem]
    """The items on this page. May be empty, even if there are more items to be found.
    The end is only guarranteed to be reached when the returned cursor is None
    """
    cursor: Optional[int]
    """The cursor to use for the next call, or None if there are no more items to be found"""


@dataclass
class ClientFlowGraphAnalysisReadReachableResultLockLost:
    type: Literal["lock_lost"]
    """
    - `lock_lost`: the lock is no longer held
    """


@dataclass
class ClientFlowGraphAnalysisReadReachableResultNotFound:
    type: Literal["not_found"]
    """
    - `not_found`: the data is not in the cache
    """


@dataclass
class ClientFLowGraphAnalysisReadReachableResultCorrupted:
    type: Literal["corrupted"]
    """
    - `corrupted`: we detected that one of our invariants was violated
    """


ClientFlowGraphAnalysisReadReachableResult = Union[
    ClientFlowGraphAnalysisReadReachableResultSuccess,
    ClientFlowGraphAnalysisReadReachableResultLockLost,
    ClientFlowGraphAnalysisReadReachableResultNotFound,
    ClientFLowGraphAnalysisReadReachableResultCorrupted,
]


async def client_flow_graph_analysis_read_reachable(
    redis: redis.asyncio.client.Redis,
    /,
    *,
    graph_id: bytes,
    version: int,
    lock_type: Literal["reader", "writer"],
    lock_uid: bytes,
    source_flow_slug: bytes,
    inverted: bool,
    now: int,
    cursor: int,
    max_steps: Optional[int],
) -> Optional[ClientFlowGraphAnalysisReadReachableResult]:
    """Reads the already computed reachable values within the graph implied by the
    given data uid, using the reader or writer lock with the given uid to guard the
    read. If you hold the lock but only some of the data was written (i.e, the
    last writer was interrupted), the data is ignored. This is safe for readers
    as well as writers, since a partial write is treated equivalently to an
    empty key by all parties except for a writer which is using a script
    specifically expecting a partial value (`write_batch`), which must not exist
    since you have a lock and aren't using that script

    Args:
        redis (redis.asyncio.client.Redis): The redis client
        graph_id (bytes): identifies the configuration used to generate the graph
        version (int): the value of `client_flow_graph_analysis:version` when the lock was acquired
        lock_type (Literal["reader", "writer"]): the type of lock you hold
        lock_uid (bytes): the uid of the lock you hold
        source_flow_slug (bytes): the slug of the flow you are reading from
        inverted (bool): whether to read the inverted graph (True) or normal graph (False)
        now (int): the current time, in seconds since the epoch
        cursor (int): the cursor for scanning; use 0 to start from the beginning
        max_steps (int, None): when not None, reads only flows that are reachable within this
            number of steps (effects the key being read)

    Returns:
        ClientFlowGraphAnalysisReadReachableResult, None: The result. None if
            executed within a transaction, since the result is not known until
            the transaction is executed.

    Raises:
        NoScriptError: If the script is not loaded into redis
    """
    res = await redis.evalsha(
        CLIENT_FLOW_GRAPH_ANALYSIS_READ_REACHABLE_LUA_SCRIPT_HASH,
        0,
        graph_id,  # type: ignore
        str(version).encode("ascii"),  # type: ignore
        b"1" if lock_type == "writer" else b"2",  # type: ignore
        lock_uid,  # type: ignore
        source_flow_slug,  # type: ignore
        b"1" if inverted else b"0",  # type: ignore
        str(now).encode("ascii"),  # type: ignore
        str(cursor).encode("ascii"),  # type: ignore
        *([] if max_steps is None else [str(max_steps).encode("ascii")]),  # type: ignore
    )
    if res is redis:
        return None
    return parse_client_flow_graph_analysis_read_reachable_result(res)


async def safe_client_flow_graph_analysis_read_reachable(
    itgs: Itgs,
    /,
    *,
    graph_id: bytes,
    version: int,
    lock_type: Literal["reader", "writer"],
    lock_uid: bytes,
    source_flow_slug: bytes,
    inverted: bool,
    now: int,
    cursor: int,
    max_steps: Optional[int],
) -> ClientFlowGraphAnalysisReadReachableResult:
    """Same as client_flow_graph_analysis_read_reachable but executing in the standard
    redis instance for the given itgs (not a pipeline), thus loading the script can be
    handled for you and the result is never None
    """
    redis = await itgs.redis()

    async def _prepare(force: bool):
        await ensure_client_flow_graph_analysis_read_reachable_script_exists(
            redis, force=force
        )

    async def _execute():
        return await client_flow_graph_analysis_read_reachable(
            redis,
            graph_id=graph_id,
            version=version,
            lock_type=lock_type,
            lock_uid=lock_uid,
            source_flow_slug=source_flow_slug,
            inverted=inverted,
            now=now,
            cursor=cursor,
            max_steps=max_steps,
        )

    result = await run_with_prep(_prepare, _execute)
    assert result is not None
    return result


def parse_client_flow_graph_analysis_read_reachable_result(
    res: Any,
) -> ClientFlowGraphAnalysisReadReachableResult:
    assert isinstance(res, (list, tuple)), res
    assert len(res) >= 1, res
    result_type = int(res[0])
    if result_type == 1:
        assert len(res) >= 3, res
        assert isinstance(res[1], (list, tuple)), res

        flow_items: List[ClientFlowGraphAnalysisReadReachableItem] = []
        for item in res[1]:
            assert isinstance(item, (list, tuple)), res
            assert len(item) == 3, res
            assert isinstance(item[0], bytes), res
            assert isinstance(item[1], (int, bytes)), res
            assert isinstance(item[2], bytes), res
            flow_items.append(
                ClientFlowGraphAnalysisReadReachableItem(
                    slug=item[0], count=int(item[1]), first=item[2]
                )
            )
        assert isinstance(res[2], (int, bytes)), res
        next_cursor = int(res[2])

        return ClientFlowGraphAnalysisReadReachableResultSuccess(
            type="success",
            flow_items=flow_items,
            cursor=None if next_cursor == 0 else next_cursor,
        )
    if result_type == -1:
        return ClientFlowGraphAnalysisReadReachableResultLockLost(type="lock_lost")
    if result_type == -2:
        return ClientFlowGraphAnalysisReadReachableResultNotFound(type="not_found")
    if result_type == -3:
        return ClientFLowGraphAnalysisReadReachableResultCorrupted(type="corrupted")
    raise ValueError(f"Unknown result: {res}")
