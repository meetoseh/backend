from typing import Any, Literal, Optional, List, Union
import hashlib
import time
import redis.asyncio.client
from dataclasses import dataclass

from itgs import Itgs
from redis_helpers.run_with_prep import run_with_prep

JOURNAL_CHAT_JOBS_START_LUA_SCRIPT = """
local user_sub = ARGV[1]
local is_user_pro = ARGV[2] == "P"
local journal_chat_uid = ARGV[3]
local journal_entry_uid = ARGV[4]
local journal_master_key_uid = ARGV[5]
local encrypted_task_base64url = ARGV[6]
local queued_at_str = ARGV[7]
local first_event = ARGV[8]

local user_queued = redis.call("GET", "journals:count_queued_journal_chat_jobs_by_user:" .. user_sub)
if user_queued ~= false then
    local num_user_queued = tonumber(user_queued)
    local limit = is_user_pro and 3 or 1
    if num_user_queued >= limit then
        return {-1, num_user_queued, limit}
    end
end

local total_queued = (
    redis.call("LLEN", "journals:journal_chat_jobs:priority")
    + redis.call("LLEN", "journals:journal_chat_jobs:normal")
)
local limit_total_queued = is_user_pro and 100 or 10
if total_queued >= limit_total_queued then
    return {-2, total_queued, limit_total_queued}
end

redis.call("INCR", "journals:count_queued_journal_chat_jobs_by_user:" .. user_sub)
redis.call(
    "HSET",
    "journals:journal_chat_jobs:" .. journal_chat_uid,
    "starts", "0",
    "start_time", "never",
    "started_by", "never",
    "log_id", "never",
    "queued_at", queued_at_str,
    "user_sub", user_sub,
    "journal_entry_uid", journal_entry_uid,
    "journal_master_key_uid", journal_master_key_uid,
    "encrypted_task", encrypted_task_base64url
)

local event_list_key = "journal_chats:" .. journal_chat_uid .. ":events"
redis.call("RPUSH", event_list_key, first_event)
redis.call("EXPIREAT", event_list_key, tonumber(queued_at_str) + 60 * 60)
redis.call(
    "PUBLISH",
    "ps:journal_chats:" .. journal_chat_uid .. ":events",
    first_event
)
redis.call(
    "RPUSH",
    is_user_pro and "journals:journal_chat_jobs:priority" or "journals:journal_chat_jobs:normal",
    journal_chat_uid
)
redis.call(
    "PUBLISH",
    "ps:journal_chat_jobs:queued",
    "1"
)
return {1, false, false}
"""
# Note it doesn't matter if the publish happens at the end; they can't see the
# state of redis until the script completes (their requests will block), so from
# the subscribers perspective they always see the result of the entire script

JOURNAL_CHAT_JOBS_START_LUA_SCRIPT_HASH = hashlib.sha1(
    JOURNAL_CHAT_JOBS_START_LUA_SCRIPT.encode("utf-8")
).hexdigest()


_last_journal_chat_jobs_start_ensured_at: Optional[float] = None


async def ensure_journal_chat_jobs_start_script_exists(
    redis: redis.asyncio.client.Redis, *, force: bool = False
) -> None:
    """Ensures the journal_chat_jobs_start lua script is loaded into redis."""
    global _last_journal_chat_jobs_start_ensured_at

    now = time.time()
    if (
        not force
        and _last_journal_chat_jobs_start_ensured_at is not None
        and (now - _last_journal_chat_jobs_start_ensured_at < 5)
    ):
        return

    loaded: List[bool] = await redis.script_exists(
        JOURNAL_CHAT_JOBS_START_LUA_SCRIPT_HASH
    )
    if not loaded[0]:
        correct_hash = await redis.script_load(JOURNAL_CHAT_JOBS_START_LUA_SCRIPT)
        assert (
            correct_hash == JOURNAL_CHAT_JOBS_START_LUA_SCRIPT_HASH
        ), f"{correct_hash=} != {JOURNAL_CHAT_JOBS_START_LUA_SCRIPT_HASH=}"

    if (
        _last_journal_chat_jobs_start_ensured_at is None
        or _last_journal_chat_jobs_start_ensured_at < now
    ):
        _last_journal_chat_jobs_start_ensured_at = now


@dataclass
class JournalChatJobsStartRatelimited:
    type: Literal["ratelimited"]
    at: int
    limit: int


@dataclass
class JournalChatJobsStartBackpressure:
    type: Literal["backpressure"]
    at: int
    limit: int


@dataclass
class JournalChatJobsStartSucceeded:
    type: Literal["succeeded"]


JournalChatJobsStartResult = Union[
    JournalChatJobsStartRatelimited,
    JournalChatJobsStartBackpressure,
    JournalChatJobsStartSucceeded,
]


async def journal_chat_jobs_start(
    redis: redis.asyncio.client.Redis,
    /,
    *,
    user_sub: bytes,
    is_user_pro: bool,
    journal_chat_uid: bytes,
    journal_entry_uid: bytes,
    journal_master_key_uid: bytes,
    encrypted_task_base64url: bytes,
    queued_at: int,
    first_event: bytes,
) -> Optional[JournalChatJobsStartResult]:
    """Attempts to queue a journal chat job for processing. To help manage the
    complexity of this function signature, keys, key formats, and constants are
    embedded in the script.

    Args:
        redis (redis.asyncio.client.Redis): The redis client
        user_sub (bytes): the sub of the user queueing the job
        is_user_pro (bool): True if the user has Oseh+, false otherwise
        journal_chat_uid (bytes): the uid of the journal chat being queued; this
          is essentially the uid to assign to the job
        journal_entry_uid (bytes): the uid of the journal entry being edited
        journal_master_key_uid (bytes): the uid of the journal master key used to
          encrypt the task
        encrypted_task_base64url (bytes): the task (a json object), stringified,
          Fernet encrypted, base64url encoded, and finally ascii encoded. See
          `docs/redis/keys.md` under `journals:journal_chat_jobs:{journal_chat_uid}`
          for details on how the task should be constructed.
        queued_at (int): the time the job was queued, in seconds since the epoch
        first_event (bytes): the first event to queue to the journal chat events list,
          typically this is a passthrough `thinking-spinner` event encrypted with the same
          journal master key as the task

    Returns:
        bool, None: True if the value was updated, False otherwise. None if executed
            within a transaction, since the result is not known until the
            transaction is executed.

    Raises:
        NoScriptError: If the script is not loaded into redis
    """
    res = await redis.evalsha(
        JOURNAL_CHAT_JOBS_START_LUA_SCRIPT_HASH,
        0,
        user_sub,  # type: ignore
        b"P" if is_user_pro else b"F",  # type: ignore
        journal_chat_uid,  # type: ignore
        journal_entry_uid,  # type: ignore
        journal_master_key_uid,  # type: ignore
        encrypted_task_base64url,  # type: ignore
        str(queued_at).encode("ascii"),  # type: ignore
        first_event,  # type: ignore
    )
    if res is redis:
        return None
    return parse_journal_chat_jobs_start_result(res)


async def safe_journal_chat_jobs_start(
    itgs: Itgs,
    /,
    *,
    user_sub: bytes,
    is_user_pro: bool,
    journal_chat_uid: bytes,
    journal_entry_uid: bytes,
    journal_master_key_uid: bytes,
    encrypted_task_base64url: bytes,
    queued_at: int,
    first_event: bytes,
) -> JournalChatJobsStartResult:
    """Same as journal_chat_job_start, but always runs in the standard redis
    instance of the given itgs and thus doesn't need an optional return value
    """
    redis = await itgs.redis()

    async def prepare(force: bool):
        await ensure_journal_chat_jobs_start_script_exists(redis, force=force)

    async def execute():
        return await journal_chat_jobs_start(
            redis,
            user_sub=user_sub,
            is_user_pro=is_user_pro,
            journal_chat_uid=journal_chat_uid,
            journal_entry_uid=journal_entry_uid,
            journal_master_key_uid=journal_master_key_uid,
            encrypted_task_base64url=encrypted_task_base64url,
            queued_at=queued_at,
            first_event=first_event,
        )

    res = await run_with_prep(prepare, execute)
    assert res is not None
    return res


def parse_journal_chat_jobs_start_result(raw: Any) -> JournalChatJobsStartResult:
    """Parses the response from redis to the journal chat jobs start lua script
    into a more interpretable value
    """
    assert isinstance(raw, (list, tuple)), raw
    type_ = int(raw[0])

    if type_ == -1:
        assert len(raw) >= 3, raw
        at = int(raw[1])
        limit = int(raw[2])
        assert at >= limit, raw

        return JournalChatJobsStartRatelimited(type="ratelimited", at=at, limit=limit)
    elif type_ == -2:
        assert len(raw) >= 3, raw
        at = int(raw[1])
        limit = int(raw[2])
        assert at >= limit, raw
        return JournalChatJobsStartBackpressure(type="backpressure", at=at, limit=limit)
    elif type_ == 1:
        return JournalChatJobsStartSucceeded(type="succeeded")

    raise ValueError(f"bad return value: {raw} (expected -1, -2, or 1)")
