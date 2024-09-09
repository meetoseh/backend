from typing import Any, Literal, Optional, List, Union
import hashlib
import time
import redis.asyncio.client
from dataclasses import dataclass

from itgs import Itgs
from redis_helpers.run_with_prep import run_with_prep

CLIENT_FLOW_GRAPH_ANALYSIS_WRITE_BATCH_LUA_SCRIPT = """
local graph_id = ARGV[1]
local version_str = ARGV[2]
local lock_uid = ARGV[3]
local inverted = ARGV[4] == "1"
local source = ARGV[5]
local max_steps_str = ARGV[6] ~= '-' and ARGV[6]
local is_first = ARGV[7] == "1"
local is_last = ARGV[8] == "1"
local batch_length_str = ARGV[9]
local batch_start_idx = 9

local base_key_meta = 'client_flow_graph_analysis:' .. graph_id .. ':' .. version_str
local writer_lock_key = base_key_meta .. ':writer'

local current_writer = redis.call('GET', writer_lock_key)
if current_writer ~= lock_uid then
    return -1
end

local meta_key = base_key_meta .. ':meta'
local data_uid = redis.call('HGET', meta_key, 'uid')
if data_uid == false then
    return -2
end
local expire_time_str = redis.call('HGET', meta_key, 'expires_at')
if expire_time_str == false then
    return -2
end

local reachable_key =
    'client_flow_graph_analysis:'
    .. data_uid
    .. ':'
    .. (inverted and 'inverted_' or '')
    .. 'reachable:'
    .. source
    .. (max_steps_str ~= false and (':' .. max_steps_str) or '')

if is_first then
    local cursor = nil
    while cursor ~= '0' do
        local scan_result = redis.call('SSCAN', reachable_key, cursor or 0)
        cursor = scan_result[1]

        for _, target in ipairs(scan_result[2]) do
            redis.call('DEL', reachable_key .. ':paths:' .. target)
        end
    end
    redis.call('DEL', reachable_key)
end

local batch_length = tonumber(batch_length_str)
local argv_index = batch_start_idx + 1
for batch_idx = 1, batch_length do
    local target = ARGV[argv_index]
    argv_index = argv_index + 1
    local num_items = tonumber(ARGV[argv_index])
    argv_index = argv_index + 1

    redis.call('SADD', reachable_key, target)

    local target_key = reachable_key .. ':paths:' .. target
    for item_idx = 1, num_items do
        local item_str = ARGV[argv_index]
        argv_index = argv_index + 1

        redis.call('RPUSH', target_key, item_str)
    end
    redis.call('EXPIREAT', target_key, expire_time_str)
end

if is_last then
    redis.call('SADD', reachable_key, '__computed__')
end

redis.call('EXPIREAT', reachable_key, expire_time_str)

return 1
"""
CLIENT_FLOW_GRAPH_ANALYSIS_WRITE_BATCH_LUA_SCRIPT_HASH = hashlib.sha1(
    CLIENT_FLOW_GRAPH_ANALYSIS_WRITE_BATCH_LUA_SCRIPT.encode("utf-8")
).hexdigest()


_last_client_flow_graph_analysis_write_batch_ensured_at: Optional[float] = None


async def ensure_client_flow_graph_analysis_write_batch_script_exists(
    redis: redis.asyncio.client.Redis, *, force: bool = False
) -> None:
    """Ensures the client_flow_graph_analysis_write_batch lua script is loaded into redis."""
    global _last_client_flow_graph_analysis_write_batch_ensured_at

    now = time.time()
    if (
        not force
        and _last_client_flow_graph_analysis_write_batch_ensured_at is not None
        and (now - _last_client_flow_graph_analysis_write_batch_ensured_at < 5)
    ):
        return

    loaded: List[bool] = await redis.script_exists(
        CLIENT_FLOW_GRAPH_ANALYSIS_WRITE_BATCH_LUA_SCRIPT_HASH
    )
    if not loaded[0]:
        correct_hash = await redis.script_load(
            CLIENT_FLOW_GRAPH_ANALYSIS_WRITE_BATCH_LUA_SCRIPT
        )
        assert (
            correct_hash == CLIENT_FLOW_GRAPH_ANALYSIS_WRITE_BATCH_LUA_SCRIPT_HASH
        ), f"{correct_hash=} != {CLIENT_FLOW_GRAPH_ANALYSIS_WRITE_BATCH_LUA_SCRIPT_HASH=}"

    if (
        _last_client_flow_graph_analysis_write_batch_ensured_at is None
        or _last_client_flow_graph_analysis_write_batch_ensured_at < now
    ):
        _last_client_flow_graph_analysis_write_batch_ensured_at = now


@dataclass
class ClientFlowGraphAnalysisWriteBatchResultSuccess:
    type: Literal["success"]
    """
    - `success`: indicates the batch was written
    """


@dataclass
class ClientFlowGraphAnalysisWriteBatchResultLockLost:
    type: Literal["lock_lost"]
    """
    - `lock_lost`: indicates the lock was lost
    """


@dataclass
class ClientFlowGraphAnalysisWriteBatchResultCorrupted:
    type: Literal["corrupted"]
    """
    - `corrupted`: indicates an invariant was violated
    """


ClientFlowGraphAnalysisWriteBatchResult = Union[
    ClientFlowGraphAnalysisWriteBatchResultSuccess,
    ClientFlowGraphAnalysisWriteBatchResultLockLost,
    ClientFlowGraphAnalysisWriteBatchResultCorrupted,
]


async def client_flow_graph_analysis_write_batch(
    redis: redis.asyncio.client.Redis,
    /,
    *,
    graph_id: bytes,
    version: int,
    lock_uid: bytes,
    inverted: bool,
    source: bytes,
    max_steps: Optional[int],
    is_first: bool,
    is_last: bool,
    batch: List[bytes],
) -> Optional[ClientFlowGraphAnalysisWriteBatchResult]:
    """Writes a batch of data to the client flow graph analysis, guarded by the write lock
    you hold with the given uid.

    The batch is a serialization representing the following structure:

    ```
    [
        {"target": "string", "items": [{"type": "edge", ...}, ...]},
        ...
    ]
    ```

    Where slug is referring to the flow slug to append to and the items are lists
    to append to the paths to get to from the source to the target in the given number
    of steps. The serialization is as follows:

    - number of different targets (as an ascii-encoded string)
    - REPEATED
        - target
        - number of items (as an ascii-encoded string, never 0)
        - REPEATED
            - item (as a jsonified, utf8-encoded string)

    You must guarrantee symmetric and unnested `is_first` and `is_last` calls. You
    must also guarrantee that when `is_last` is true, all the targets for the source
    have been written and the `{"type":"done"}` final entry has been written to each of them.

    When `is_first` is set, any old data is discarded. When `is_last` is set, the special
    `__computed__` value is included in the set (essentially committing the data).


    Args:
        redis (redis.asyncio.client.Redis): The redis client
        graph_id (bytes): the identifier for the graph you are writing to
        version (int): the value of `client_flow_graph_analysis:version` when you acquired your lock
        lock_uid (bytes): the uid of the write lock you acquired
        inverted (bool): True if you are writing to the inverted graph, False if you are writing
            to the normal graph
        source (bytes): this script allows you to upload the paths from a single source. This
            is the source within all the paths. Do not include the source in the paths (start
            at the first edge)
        max_steps (int, None): Whether you are computing paths from an unlimited number of steps
            from the source (None), or limited to a maximum number of steps (in which case, the
            maximum number of steps you are walking)
        is_first (bool): True for the first batch since the last `is_last` call, False otherwise
        is_last (bool): True for the last batch, False otherwise. Until set, the data
            is essentially uncommitted (it will be deleted by the next reader/writer). You may
            set is_first and is_last to True at the same time, provided the batch completely
            describes the paths from the source in the given number of steps.

    Returns:
        ClientFlowGraphAnalysisWriteBatchResult: The result. None if executed
            within a transaction, since the result is not known until the
            transaction is executed.

    Raises:
        NoScriptError: If the script is not loaded into redis
    """
    res = await redis.evalsha(
        CLIENT_FLOW_GRAPH_ANALYSIS_WRITE_BATCH_LUA_SCRIPT_HASH,
        0,
        graph_id,  # type: ignore
        str(version).encode("ascii"),  # type: ignore
        lock_uid,  # type: ignore
        b"1" if inverted else b"0",  # type: ignore
        source,  # type: ignore
        b"-" if max_steps is None else str(max_steps).encode("ascii"),  # type: ignore
        b"1" if is_first else b"0",  # type: ignore
        b"1" if is_last else b"0",  # type: ignore
        *batch,  # type: ignore
    )
    if res is redis:
        return None
    return parse_client_flow_graph_analysis_write_batch_result(res)


async def safe_client_flow_graph_analysis_write_batch(
    itgs: Itgs,
    /,
    *,
    graph_id: bytes,
    version: int,
    lock_uid: bytes,
    inverted: bool,
    source: bytes,
    max_steps: Optional[int],
    is_first: bool,
    is_last: bool,
    batch: List[bytes],
) -> ClientFlowGraphAnalysisWriteBatchResult:
    """Same as client_flow_graph_analysis_write_batch, but always runs in the standard redis
    instance of the given itgs and thus doesn't need an optional return value
    """
    redis = await itgs.redis()

    async def prepare(force: bool):
        await ensure_client_flow_graph_analysis_write_batch_script_exists(
            redis, force=force
        )

    async def execute():
        return await client_flow_graph_analysis_write_batch(
            redis,
            graph_id=graph_id,
            version=version,
            lock_uid=lock_uid,
            inverted=inverted,
            source=source,
            max_steps=max_steps,
            is_first=is_first,
            is_last=is_last,
            batch=batch,
        )

    res = await run_with_prep(prepare, execute)
    assert res is not None
    return res


def parse_client_flow_graph_analysis_write_batch_result(
    raw: Any,
) -> ClientFlowGraphAnalysisWriteBatchResult:
    """Parses the response from redis to the journal chat jobs start lua script
    into a more interpretable value
    """
    assert isinstance(raw, (bytes, int)), raw
    return_type = int(raw)

    if return_type == 1:
        return ClientFlowGraphAnalysisWriteBatchResultSuccess(
            type="success",
        )
    elif return_type == -1:
        return ClientFlowGraphAnalysisWriteBatchResultLockLost(
            type="lock_lost",
        )
    elif return_type == -2:
        return ClientFlowGraphAnalysisWriteBatchResultCorrupted(
            type="corrupted",
        )

    raise ValueError(f"bad return value: {raw} (expected -1, -2, or 1)")
