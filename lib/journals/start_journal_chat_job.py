import gzip
import secrets
from typing import Dict, List, Literal, Union, cast
from itgs import Itgs
from dataclasses import dataclass

from lib.journals.journal_chat_redis_packet import (
    EventBatchPacketDataItemDataThinkingSpinner,
    JournalChatRedisPacketPassthrough,
)
from lib.journals.journal_chat_task import JournalChatTask
from lib.journals.journal_entry_item_data import JournalEntryItemData
from lib.journals.journal_chat_job_stats import JournalChatJobStats
from lib.journals.master_keys import (
    GetJournalMasterKeyForDecryptionResult,
    GetJournalMasterKeyForDecryptionResultSuccess,
    GetJournalMasterKeyForEncryptionResult,
    get_journal_master_key_for_decryption,
    get_journal_master_key_for_encryption,
)
from lib.journals.serialize_journal_chat_event import serialize_journal_chat_event
from lib.redis_stats_preparer import RedisStatsPreparer
from redis_helpers.journal_chat_jobs_start import (
    safe_journal_chat_jobs_start,
)
import unix_dates
from users.lib.entitlements import get_entitlement
from users.lib.timezones import get_user_timezone
import pytz


@dataclass
class StartJournalChatJobResultLocked:
    type: Literal["locked"]
    """
    - `locked`: for the journal entry with the given uid there is already a
      journal chat job responsible for streaming and/or modifying the items
    """
    journal_chat_uid: str
    """The UID of the journal chat job that is locking the journal entry"""


@dataclass
class StartJournalChatJobResultRatelimited:
    type: Literal["ratelimited"]
    """
    - `ratelimited`: the user exceeded the maximum number of a resource
    """
    resource: Literal["user_queued_jobs", "total_queued_jobs"]
    """
    the resource that was exceeded
    - `user_queued_jobs`: the number of jobs by the user which have not completed processing yet
    - `total_queued_jobs`: the number of jobs in total which have not completed processing yet
    """
    at: int
    """how many of the resource they have consumed"""
    limit: int
    """the limit for their account"""


@dataclass
class StartJournalChatJobResultUserNotFound:
    type: Literal["user_not_found"]
    """
    - `user_not_found`: the user could not be found
    """
    user_sub: str
    """The user sub that was not found"""


@dataclass
class StartJournalChatJobResultEncryptionFailed:
    type: Literal["encryption_failed"]
    """
    - `encryption_failed`: something went wrong related to journey encryption
    """
    master_key: GetJournalMasterKeyForEncryptionResult
    """
    The result from trying to get/create the key for encryption
    """


@dataclass
class StartJournalChatJobResultJournalEntryNotFound:
    type: Literal["journal_entry_not_found"]
    """
    - `journal_entry_not_found`: the journal entry could not be found
    """
    journal_entry_uid: str
    """The journal entry uid that was not found"""


@dataclass
class StartJournalChatJobResultJournalEntryItemNotFound:
    type: Literal["journal_entry_item_not_found"]
    """
    - `journal_entry_item_not_found`: the journal entry item could not be found
    """
    journal_entry_item_uid: str
    """The journal entry item uid that was not found"""


@dataclass
class StartJournalChatJobResultDecryptionFailed:
    type: Literal["decryption_failed"]
    """
    - `decryption_failed`: something went wrong related to journey decryption
    """
    master_key: GetJournalMasterKeyForDecryptionResult
    """
    The result from trying to get the master key for decryption
    """


@dataclass
class StartJournalChatJobResultBadState:
    type: Literal["bad_state"]
    """
    - `bad_state`: the journal entry is not in the correct state for the desired operation
    """
    detail: str
    """More information"""


@dataclass
class CreateJournalEntryWithGreetingSuccess:
    type: Literal["success"]
    """
    - `success`: the job was successfully started
    """
    journal_entry_uid: str
    """The journal entry uid that was created"""
    journal_chat_uid: str
    """The journal chat uid that was created"""


@dataclass
class AddJournalEntryItemSuccess:
    type: Literal["success"]
    """
    - `success`: the job was successfully started
    """
    journal_chat_uid: str
    """The journal chat uid that was created"""


@dataclass
class RefreshJournalEntryItemSuccess:
    type: Literal["success"]
    """
    - `success`: the job was successfully started
    """
    journal_chat_uid: str
    """The journal chat uid that was created"""


@dataclass
class SyncJournalEntrySuccess:
    type: Literal["success"]
    """
    - `success`: the job was successfully started
    """
    journal_chat_uid: str
    """The journal chat uid that was created"""


system_timezone = pytz.timezone("America/Los_Angeles")


async def create_journal_entry_with_greeting(
    itgs: Itgs,
    /,
    *,
    user_sub: str,
    now: float,
) -> Union[
    StartJournalChatJobResultLocked,
    StartJournalChatJobResultRatelimited,
    StartJournalChatJobResultUserNotFound,
    StartJournalChatJobResultEncryptionFailed,
    CreateJournalEntryWithGreetingSuccess,
]:
    """Creates a new journal entry for the user with the given sub, then starts
    a job to add a greeting message to that new journal entry (a journal chat).

    This will not attempt to limit the number of journal entries by the user, or
    try to reuse them. However, it will prevent an excessive number of journal
    chat jobs from being queued, either in total or by the user.

    Args:
        itgs (Itgs): the integrations to (re)use
        user_sub (str): the sub of the user to create a new journal entry for
        now (float): the current time in seconds since the unix epoch
    """
    system_unix_date = unix_dates.unix_timestamp_to_unix_date(now, tz=system_timezone)
    stats = JournalChatJobStats(RedisStatsPreparer())
    stats.incr_requested(type=b"greeting", unix_date=system_unix_date)

    conn = await itgs.conn()
    cursor = conn.cursor()

    user_timezone = await get_user_timezone(itgs, user_sub=user_sub)
    user_now_unix_date = unix_dates.unix_timestamp_to_unix_date(now, tz=user_timezone)

    pro_entitlement = await get_entitlement(itgs, user_sub=user_sub, identifier="pro")
    if pro_entitlement is None:
        stats.incr_failed_to_queue_simple(
            requested_at_unix_date=system_unix_date,
            type=b"greeting",
            reason=b"user_not_found",
        )
        await stats.stats.store(itgs)
        return StartJournalChatJobResultUserNotFound(
            type="user_not_found", user_sub=user_sub
        )

    journal_master_key = await get_journal_master_key_for_encryption(
        itgs, user_sub=user_sub, now=now
    )
    if journal_master_key.type != "success":
        stats.incr_failed_to_queue_simple(
            requested_at_unix_date=system_unix_date,
            type=b"greeting",
            reason=b"encryption_failed",
        )
        await stats.stats.store(itgs)
        return StartJournalChatJobResultEncryptionFailed(
            type="encryption_failed",
            master_key=journal_master_key,
        )

    journal_chat_uid = f"oseh_jc_{secrets.token_urlsafe(16)}"
    journal_entry_uid = f"oseh_jne_{secrets.token_urlsafe(16)}"

    response = await cursor.execute(
        """
INSERT INTO journal_entries (
    uid,
    user_id,
    flags,
    created_at,
    created_unix_date
)
SELECT
    ?, users.id, ?, ?, ?
FROM users WHERE users.sub=?
        """,
        (
            journal_entry_uid,
            0,
            now,
            user_now_unix_date,
            user_sub,
        ),
    )

    if response.rows_affected is None or response.rows_affected < 1:
        stats.incr_failed_to_queue_simple(
            requested_at_unix_date=system_unix_date,
            type=b"greeting",
            reason=b"user_not_found",
        )
        await stats.stats.store(itgs)
        return StartJournalChatJobResultUserNotFound(
            type="user_not_found",
            user_sub=user_sub,
        )

    encrypted_task_base64url = journal_master_key.journal_master_key.encrypt_at_time(
        JournalChatTask.__pydantic_serializer__.to_json(
            JournalChatTask(
                type="greeting",
                include_previous_history=True,
                replace_entry_item_uid=None,
            )
        ),
        int(now),
    )
    first_event = serialize_journal_chat_event(
        journal_master_key=journal_master_key,
        event=JournalChatRedisPacketPassthrough(
            counter=0,
            type="passthrough",
            event=EventBatchPacketDataItemDataThinkingSpinner(
                type="thinking-spinner",
                message="Waiting in the "
                + ("priority" if pro_entitlement.is_active else "regular")
                + " queue",
                detail=(
                    "Upgrade to Oseh+ to access the priority queue"
                    if not pro_entitlement.is_active
                    else None
                ),
            ),
        ),
        now=now,
    )

    result = await safe_journal_chat_jobs_start(
        itgs,
        user_sub=user_sub.encode("utf-8"),
        is_user_pro=pro_entitlement.is_active,
        journal_chat_uid=journal_chat_uid.encode("utf-8"),
        journal_entry_uid=journal_entry_uid.encode("utf-8"),
        journal_master_key_uid=journal_master_key.journal_master_key_uid.encode(
            "utf-8"
        ),
        encrypted_task_base64url=encrypted_task_base64url,
        queued_at=int(now),
        first_event=first_event,
    )
    if result.type != "succeeded":
        await cursor.execute(
            "DELETE FROM journal_entries WHERE uid=?", (journal_entry_uid,)
        )

    if result.type == "backpressure":
        stats.incr_failed_to_queue_ratelimited(
            requested_at_unix_date=system_unix_date,
            type=b"greeting",
            resource=b"total_queued_jobs",
            at=result.at,
            limit=result.limit,
        )
        await stats.stats.store(itgs)
        return StartJournalChatJobResultRatelimited(
            type="ratelimited",
            resource="total_queued_jobs",
            at=result.at,
            limit=result.limit,
        )
    if result.type == "ratelimited":
        stats.incr_failed_to_queue_ratelimited(
            requested_at_unix_date=system_unix_date,
            type=b"greeting",
            resource=b"user_queued_jobs",
            at=result.at,
            limit=result.limit,
        )
        await stats.stats.store(itgs)
        return StartJournalChatJobResultRatelimited(
            type="ratelimited",
            resource="user_queued_jobs",
            at=result.at,
            limit=result.limit,
        )
    if result.type == "locked":
        stats.incr_failed_to_queue_simple(
            requested_at_unix_date=system_unix_date, type=b"greeting", reason=b"locked"
        )
        await stats.stats.store(itgs)
        return StartJournalChatJobResultLocked(
            type="locked",
            journal_chat_uid=result.locked_by_journal_chat_uid.decode("utf-8"),
        )

    assert result.type == "succeeded"
    stats.incr_queued(requested_at_unix_date=system_unix_date, type=b"greeting")
    await stats.stats.store(itgs)
    return CreateJournalEntryWithGreetingSuccess(
        type="success",
        journal_entry_uid=journal_entry_uid,
        journal_chat_uid=journal_chat_uid,
    )


async def refresh_journal_entry_greeting(
    itgs: Itgs,
    /,
    *,
    user_sub: str,
    journal_entry_uid: str,
    journal_entry_item_uid: str,
    now: float,
) -> Union[
    StartJournalChatJobResultLocked,
    StartJournalChatJobResultRatelimited,
    StartJournalChatJobResultJournalEntryNotFound,
    StartJournalChatJobResultJournalEntryItemNotFound,
    StartJournalChatJobResultDecryptionFailed,
    StartJournalChatJobResultBadState,
    StartJournalChatJobResultEncryptionFailed,
    RefreshJournalEntryItemSuccess,
]: ...


async def add_journal_entry_chat(
    itgs: Itgs,
    /,
    *,
    user_sub: str,
    journal_entry_uid: str,
    now: float,
    include_previous_history: bool,
) -> Union[
    StartJournalChatJobResultLocked,
    StartJournalChatJobResultRatelimited,
    StartJournalChatJobResultUserNotFound,
    StartJournalChatJobResultJournalEntryNotFound,
    StartJournalChatJobResultDecryptionFailed,
    StartJournalChatJobResultBadState,
    StartJournalChatJobResultEncryptionFailed,
    AddJournalEntryItemSuccess,
]:
    """Fetches and decrypts the journal entry with the given uid for the user
    with the given sub. Assuming the entry is in an appropriate state to add
    a new system message, i.e., the last message was a chat from the user, this
    will queue a job to add a system message to the journal entry.

    If the journal entry is mutated before this job completes, its the jobs
    responsibility to detect that and avoid adding the system message.

    Args:
        itgs (Itgs): the integrations to (re)use
        user_sub (str): the sub of the user to add a system message for
        journal_entry_uid (str): the uid of the journal entry to add a system
            message to
        now (float): the current time in seconds since the unix epoch
        include_previous_history (bool): Generally, false for clients with version
            73 or lower, true otherwise. Determines if we will include the greeting
            and user message in the chat state.

    Returns:
        Either that this succeeded, or why it failed
    """
    system_unix_date = unix_dates.unix_timestamp_to_unix_date(now, tz=system_timezone)
    stats = JournalChatJobStats(RedisStatsPreparer())
    stats.incr_requested(unix_date=system_unix_date, type=b"system_chat")

    pro_entitlement = await get_entitlement(itgs, user_sub=user_sub, identifier="pro")
    if pro_entitlement is None:
        stats.incr_failed_to_queue_simple(
            requested_at_unix_date=system_unix_date,
            type=b"system_chat",
            reason=b"user_not_found",
        )
        await stats.stats.store(itgs)
        return StartJournalChatJobResultUserNotFound(
            type="user_not_found", user_sub=user_sub
        )

    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    response = await cursor.executeunified3(
        (
            (
                "SELECT 1 FROM users WHERE sub = ?",
                (user_sub,),
            ),
            (
                """
SELECT 1 FROM users, journal_entries 
WHERE 
    users.sub = ? 
    AND journal_entries.uid = ? 
    AND journal_entries.user_id = users.id
                """,
                (user_sub, journal_entry_uid),
            ),
            (
                """
SELECT
    user_journal_master_keys.uid,
    journal_entry_items.master_encrypted_data
FROM users, journal_entries, journal_entry_items, user_journal_master_keys
WHERE
    users.sub = ?
    AND users.id = journal_entries.user_id
    AND journal_entries.uid = ?
    AND journal_entry_items.journal_entry_id = journal_entries.id
    AND journal_entry_items.user_journal_master_key_id = user_journal_master_keys.id
ORDER BY journal_entry_items.entry_counter ASC
                """,
                (user_sub, journal_entry_uid),
            ),
        )
    )

    if not response[0].results:
        assert not response[1].results, response
        assert not response[2].results, response
        stats.incr_failed_to_queue_simple(
            requested_at_unix_date=system_unix_date,
            type=b"system_chat",
            reason=b"user_not_found",
        )
        await stats.stats.store(itgs)
        return StartJournalChatJobResultUserNotFound(
            type="user_not_found",
            user_sub=user_sub,
        )

    if not response[1].results:
        assert not response[2].results, response
        stats.incr_failed_to_queue_simple(
            requested_at_unix_date=system_unix_date,
            type=b"system_chat",
            reason=b"journal_entry_not_found",
        )
        await stats.stats.store(itgs)
        return StartJournalChatJobResultJournalEntryNotFound(
            type="journal_entry_not_found",
            journal_entry_uid=journal_entry_uid,
        )

    if not response[2].results:
        stats.incr_failed_to_queue_simple(
            requested_at_unix_date=system_unix_date,
            type=b"system_chat",
            reason=b"bad_state",
        )
        await stats.stats.store(itgs)
        return StartJournalChatJobResultBadState(
            type="bad_state",
            detail="no items in journal entry (did you mean to create a greeting?)",
        )

    conversation: List[JournalEntryItemData] = []
    journal_master_keys_for_decr_by_uid: Dict[
        str, GetJournalMasterKeyForDecryptionResultSuccess
    ] = dict()
    for row in response[2].results:
        row_user_journal_master_key_uid = cast(str, row[0])
        row_master_encrypted_data_base64url = cast(str, row[1])

        row_journal_master_key = journal_master_keys_for_decr_by_uid.get(
            row_user_journal_master_key_uid
        )
        if row_journal_master_key is None:
            row_journal_master_key_raw = await get_journal_master_key_for_decryption(
                itgs,
                user_sub=user_sub,
                journal_master_key_uid=row_user_journal_master_key_uid,
            )
            if row_journal_master_key_raw.type != "success":
                stats.incr_failed_to_queue_simple(
                    requested_at_unix_date=system_unix_date,
                    type=b"system_chat",
                    reason=b"decryption_failed",
                )
                await stats.stats.store(itgs)
                return StartJournalChatJobResultDecryptionFailed(
                    type="decryption_failed",
                    master_key=row_journal_master_key_raw,
                )
            row_journal_master_key = row_journal_master_key_raw
            journal_master_keys_for_decr_by_uid[row_user_journal_master_key_uid] = (
                row_journal_master_key
            )

        conversation.append(
            JournalEntryItemData.model_validate_json(
                gzip.decompress(
                    row_journal_master_key.journal_master_key.decrypt(
                        row_master_encrypted_data_base64url, ttl=None
                    )
                )
            )
        )
    del journal_master_keys_for_decr_by_uid

    if conversation[-1].type != "chat":
        stats.incr_failed_to_queue_simple(
            requested_at_unix_date=system_unix_date,
            type=b"system_chat",
            reason=b"bad_state",
        )
        await stats.stats.store(itgs)
        return StartJournalChatJobResultBadState(
            type="bad_state",
            detail="last item in journal entry was not a chat",
        )

    if conversation[-1].display_author != "self":
        stats.incr_failed_to_queue_simple(
            requested_at_unix_date=system_unix_date,
            type=b"system_chat",
            reason=b"bad_state",
        )
        await stats.stats.store(itgs)
        return StartJournalChatJobResultBadState(
            type="bad_state",
            detail="last chat in journal entry was not from the user",
        )
    del conversation

    journal_master_key = await get_journal_master_key_for_encryption(
        itgs, user_sub=user_sub, now=now
    )
    if journal_master_key.type != "success":
        stats.incr_failed_to_queue_simple(
            requested_at_unix_date=system_unix_date,
            type=b"system_chat",
            reason=b"encryption_failed",
        )
        await stats.stats.store(itgs)
        return StartJournalChatJobResultEncryptionFailed(
            type="encryption_failed",
            master_key=journal_master_key,
        )

    encrypted_task_base64url = journal_master_key.journal_master_key.encrypt(
        JournalChatTask.__pydantic_serializer__.to_json(
            JournalChatTask(
                type="chat",
                replace_entry_item_uid=None,
                include_previous_history=include_previous_history,
            )
        )
    )

    journal_chat_uid = f"oseh_jc_{secrets.token_urlsafe(16)}"
    first_event = serialize_journal_chat_event(
        journal_master_key=journal_master_key,
        event=JournalChatRedisPacketPassthrough(
            counter=0,
            type="passthrough",
            event=EventBatchPacketDataItemDataThinkingSpinner(
                type="thinking-spinner",
                message="Waiting in the "
                + ("priority" if pro_entitlement.is_active else "regular")
                + " queue",
                detail=(
                    "Upgrade to Oseh+ to access the priority queue"
                    if not pro_entitlement.is_active
                    else None
                ),
            ),
        ),
        now=now,
    )
    result = await safe_journal_chat_jobs_start(
        itgs,
        user_sub=user_sub.encode("utf-8"),
        is_user_pro=pro_entitlement.is_active,
        journal_chat_uid=journal_chat_uid.encode("utf-8"),
        journal_entry_uid=journal_entry_uid.encode("utf-8"),
        journal_master_key_uid=journal_master_key.journal_master_key_uid.encode(
            "utf-8"
        ),
        encrypted_task_base64url=encrypted_task_base64url,
        queued_at=int(now),
        first_event=first_event,
    )

    if result.type == "backpressure":
        stats.incr_failed_to_queue_ratelimited(
            requested_at_unix_date=system_unix_date,
            type=b"system_chat",
            resource=b"total_queued_jobs",
            at=result.at,
            limit=result.limit,
        )
        await stats.stats.store(itgs)
        return StartJournalChatJobResultRatelimited(
            type="ratelimited",
            resource="total_queued_jobs",
            at=result.at,
            limit=result.limit,
        )
    if result.type == "ratelimited":
        stats.incr_failed_to_queue_ratelimited(
            requested_at_unix_date=system_unix_date,
            type=b"system_chat",
            resource=b"user_queued_jobs",
            at=result.at,
            limit=result.limit,
        )
        await stats.stats.store(itgs)
        return StartJournalChatJobResultRatelimited(
            type="ratelimited",
            resource="user_queued_jobs",
            at=result.at,
            limit=result.limit,
        )
    if result.type == "locked":
        stats.incr_failed_to_queue_simple(
            requested_at_unix_date=system_unix_date,
            type=b"system_chat",
            reason=b"locked",
        )
        await stats.stats.store(itgs)
        return StartJournalChatJobResultLocked(
            type="locked",
            journal_chat_uid=result.locked_by_journal_chat_uid.decode("utf-8"),
        )

    assert result.type == "succeeded"
    stats.incr_queued(requested_at_unix_date=system_unix_date, type=b"system_chat")
    await stats.stats.store(itgs)
    return AddJournalEntryItemSuccess(
        type="success",
        journal_chat_uid=journal_chat_uid,
    )


async def refresh_journal_entry_chat(
    itgs: Itgs,
    /,
    *,
    user_sub: str,
    journal_entry_uid: str,
    journal_entry_item_uid: str,
    now: float,
) -> Union[
    StartJournalChatJobResultLocked,
    StartJournalChatJobResultRatelimited,
    StartJournalChatJobResultJournalEntryNotFound,
    StartJournalChatJobResultJournalEntryItemNotFound,
    StartJournalChatJobResultDecryptionFailed,
    StartJournalChatJobResultBadState,
    StartJournalChatJobResultEncryptionFailed,
    RefreshJournalEntryItemSuccess,
]: ...


async def add_journal_entry_reflection_question(
    itgs: Itgs,
    /,
    *,
    user_sub: str,
    journal_entry_uid: str,
    now: float,
) -> Union[
    StartJournalChatJobResultLocked,
    StartJournalChatJobResultRatelimited,
    StartJournalChatJobResultJournalEntryNotFound,
    StartJournalChatJobResultDecryptionFailed,
    StartJournalChatJobResultBadState,
    StartJournalChatJobResultEncryptionFailed,
    AddJournalEntryItemSuccess,
]: ...


async def refresh_journal_entry_reflection_question(
    itgs: Itgs,
    /,
    *,
    user_sub: str,
    journal_entry_uid: str,
    journal_entry_item_uid: str,
    now: float,
) -> Union[
    StartJournalChatJobResultLocked,
    StartJournalChatJobResultRatelimited,
    StartJournalChatJobResultJournalEntryNotFound,
    StartJournalChatJobResultJournalEntryItemNotFound,
    StartJournalChatJobResultDecryptionFailed,
    StartJournalChatJobResultBadState,
    StartJournalChatJobResultEncryptionFailed,
    RefreshJournalEntryItemSuccess,
]: ...


async def sync_journal_entry(
    itgs: Itgs, /, *, user_sub: str, journal_entry_uid: str, now: float
) -> Union[
    StartJournalChatJobResultLocked,
    StartJournalChatJobResultRatelimited,
    StartJournalChatJobResultUserNotFound,
    StartJournalChatJobResultEncryptionFailed,
    SyncJournalEntrySuccess,
]:
    """Creates a new journal chat job which just echoes the current contents
    of the journal entry with the given uid.

    Args:
        itgs (Itgs): the integrations to (re)use
        user_sub (str): the sub of the user to sync the journal entry for
        journal_entry_uid (str): the uid of the journal entry to sync
        now (float): the current time in seconds since the unix epoch
    """
    system_unix_date = unix_dates.unix_timestamp_to_unix_date(now, tz=system_timezone)
    stats = JournalChatJobStats(RedisStatsPreparer())
    stats.incr_requested(unix_date=system_unix_date, type=b"sync")

    pro_entitlement = await get_entitlement(itgs, user_sub=user_sub, identifier="pro")
    if pro_entitlement is None:
        stats.incr_failed_to_queue_simple(
            requested_at_unix_date=system_unix_date,
            type=b"sync",
            reason=b"user_not_found",
        )
        await stats.stats.store(itgs)
        return StartJournalChatJobResultUserNotFound(
            type="user_not_found", user_sub=user_sub
        )

    journal_master_key = await get_journal_master_key_for_encryption(
        itgs, user_sub=user_sub, now=now
    )
    if journal_master_key.type != "success":
        stats.incr_failed_to_queue_simple(
            requested_at_unix_date=system_unix_date,
            type=b"sync",
            reason=b"encryption_failed",
        )
        await stats.stats.store(itgs)
        return StartJournalChatJobResultEncryptionFailed(
            type="encryption_failed",
            master_key=journal_master_key,
        )

    journal_chat_uid = f"oseh_jc_{secrets.token_urlsafe(16)}"
    encrypted_task_base64url = journal_master_key.journal_master_key.encrypt_at_time(
        JournalChatTask.__pydantic_serializer__.to_json(
            JournalChatTask(
                type="sync", replace_entry_item_uid=None, include_previous_history=True
            )
        ),
        int(now),
    )
    first_event = serialize_journal_chat_event(
        journal_master_key=journal_master_key,
        event=JournalChatRedisPacketPassthrough(
            counter=0,
            type="passthrough",
            event=EventBatchPacketDataItemDataThinkingSpinner(
                type="thinking-spinner",
                message="Waiting in the "
                + ("priority" if pro_entitlement.is_active else "regular")
                + " queue",
                detail=(
                    "Upgrade to Oseh+ to access the priority queue"
                    if not pro_entitlement.is_active
                    else None
                ),
            ),
        ),
        now=now,
    )

    result = await safe_journal_chat_jobs_start(
        itgs,
        user_sub=user_sub.encode("utf-8"),
        is_user_pro=pro_entitlement.is_active,
        journal_chat_uid=journal_chat_uid.encode("utf-8"),
        journal_entry_uid=journal_entry_uid.encode("utf-8"),
        journal_master_key_uid=journal_master_key.journal_master_key_uid.encode(
            "utf-8"
        ),
        encrypted_task_base64url=encrypted_task_base64url,
        queued_at=int(now),
        first_event=first_event,
    )
    if result.type == "backpressure":
        stats.incr_failed_to_queue_ratelimited(
            requested_at_unix_date=system_unix_date,
            type=b"sync",
            resource=b"total_queued_jobs",
            at=result.at,
            limit=result.limit,
        )
        await stats.stats.store(itgs)
        return StartJournalChatJobResultRatelimited(
            type="ratelimited",
            resource="total_queued_jobs",
            at=result.at,
            limit=result.limit,
        )
    if result.type == "ratelimited":
        stats.incr_failed_to_queue_ratelimited(
            requested_at_unix_date=system_unix_date,
            type=b"sync",
            resource=b"user_queued_jobs",
            at=result.at,
            limit=result.limit,
        )
        await stats.stats.store(itgs)
        return StartJournalChatJobResultRatelimited(
            type="ratelimited",
            resource="user_queued_jobs",
            at=result.at,
            limit=result.limit,
        )
    if result.type == "locked":
        stats.incr_failed_to_queue_simple(
            requested_at_unix_date=system_unix_date, type=b"sync", reason=b"locked"
        )
        await stats.stats.store(itgs)
        return StartJournalChatJobResultLocked(
            type="locked",
            journal_chat_uid=result.locked_by_journal_chat_uid.decode("utf-8"),
        )

    assert result.type == "succeeded"
    await stats.stats.store(itgs)
    return SyncJournalEntrySuccess(
        type="success",
        journal_chat_uid=journal_chat_uid,
    )
