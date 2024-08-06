import secrets
from typing import Literal, Union
from itgs import Itgs
from dataclasses import dataclass

from lib.journals.conversation_stream import JournalChatJobConversationStream
from lib.journals.journal_chat_redis_packet import (
    EventBatchPacketDataItemDataThinkingSpinner,
    JournalChatRedisPacketPassthrough,
)
from lib.journals.journal_chat_task import JournalChatTask
from lib.journals.journal_chat_job_stats import JournalChatJobStats
from lib.journals.master_keys import (
    GetJournalMasterKeyForDecryptionResult,
    GetJournalMasterKeyForEncryptionResult,
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

    Currently, this isn't particularly careful about race conditions, though there
    is a lock to prevent multiple jobs from being in the queue at once for the
    same journal entry

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

    stream = JournalChatJobConversationStream(
        journal_entry_uid=journal_entry_uid, user_sub=user_sub
    )
    await stream.start()

    pro_entitlement = await get_entitlement(itgs, user_sub=user_sub, identifier="pro")
    if pro_entitlement is None:
        await stream.cancel()
        stats.incr_failed_to_queue_simple(
            requested_at_unix_date=system_unix_date,
            type=b"system_chat",
            reason=b"user_not_found",
        )
        await stats.stats.store(itgs)
        return StartJournalChatJobResultUserNotFound(
            type="user_not_found", user_sub=user_sub
        )

    greeting = await stream.load_next_item(timeout=5)
    if greeting.type != "item":
        await stream.cancel()
        stats.incr_failed_to_queue_simple(
            requested_at_unix_date=system_unix_date,
            type=b"system_chat",
            reason=b"bad_state",
        )
        await stats.stats.store(itgs)
        return StartJournalChatJobResultBadState(
            type="bad_state",
            detail="failed to find greeting",
        )

    user_chat = await stream.load_next_item(timeout=5)
    if user_chat.type != "item":
        await stream.cancel()
        stats.incr_failed_to_queue_simple(
            requested_at_unix_date=system_unix_date,
            type=b"system_chat",
            reason=b"bad_state",
        )
        await stats.stats.store(itgs)
        return StartJournalChatJobResultBadState(
            type="bad_state",
            detail="failed to find user chat",
        )

    if user_chat.item.data.display_author != "self":
        await stream.cancel()
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

    blank_item = await stream.load_next_item(timeout=5)
    if blank_item.type != "finished":
        await stream.cancel()
        stats.incr_failed_to_queue_simple(
            requested_at_unix_date=system_unix_date,
            type=b"system_chat",
            reason=b"bad_state",
        )
        await stats.stats.store(itgs)
        return StartJournalChatJobResultBadState(
            type="bad_state",
            detail="expected end of conversation stream",
        )

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
    StartJournalChatJobResultUserNotFound,
    StartJournalChatJobResultJournalEntryNotFound,
    StartJournalChatJobResultDecryptionFailed,
    StartJournalChatJobResultBadState,
    StartJournalChatJobResultEncryptionFailed,
    AddJournalEntryItemSuccess,
]:
    """Fetches and decrypts the journal entry with the given uid for the user
    with the given sub. Assuming the entry is in an appropriate state to add
    a new system message, i.e., the last message was a chat from the system and
    the user has taken a journey since then, queues a job to add a reflection question.

    Currently, this isn't particularly careful about race conditions, though there
    is a lock to prevent multiple jobs from being in the queue at once for the
    same journal entry

    Args:
        itgs (Itgs): the integrations to (re)use
        user_sub (str): the sub of the user to add a system message for
        journal_entry_uid (str): the uid of the journal entry to add a system
            message to
        now (float): the current time in seconds since the unix epoch

    Returns:
        Either that this succeeded, or why it failed
    """

    system_unix_date = unix_dates.unix_timestamp_to_unix_date(now, tz=system_timezone)
    stats = JournalChatJobStats(RedisStatsPreparer())
    stats.incr_requested(unix_date=system_unix_date, type=b"reflection_question")

    stream = JournalChatJobConversationStream(
        journal_entry_uid=journal_entry_uid, user_sub=user_sub
    )
    await stream.start()

    pro_entitlement = await get_entitlement(itgs, user_sub=user_sub, identifier="pro")
    if pro_entitlement is None:
        await stream.cancel()
        stats.incr_failed_to_queue_simple(
            requested_at_unix_date=system_unix_date,
            type=b"reflection_question",
            reason=b"user_not_found",
        )
        await stats.stats.store(itgs)
        return StartJournalChatJobResultUserNotFound(
            type="user_not_found", user_sub=user_sub
        )

    greeting = await stream.load_next_item(timeout=5)
    if greeting.type != "item":
        await stream.cancel()
        stats.incr_failed_to_queue_simple(
            requested_at_unix_date=system_unix_date,
            type=b"reflection_question",
            reason=b"bad_state",
        )
        await stats.stats.store(itgs)
        return StartJournalChatJobResultBadState(
            type="bad_state",
            detail="failed to find greeting",
        )

    user_chat = await stream.load_next_item(timeout=5)
    if user_chat.type != "item":
        await stream.cancel()
        stats.incr_failed_to_queue_simple(
            requested_at_unix_date=system_unix_date,
            type=b"reflection_question",
            reason=b"bad_state",
        )
        await stats.stats.store(itgs)
        return StartJournalChatJobResultBadState(
            type="bad_state",
            detail="failed to find user chat",
        )

    system_chat = await stream.load_next_item(timeout=5)
    if system_chat.type != "item":
        await stream.cancel()
        stats.incr_failed_to_queue_simple(
            requested_at_unix_date=system_unix_date,
            type=b"reflection_question",
            reason=b"bad_state",
        )
        await stats.stats.store(itgs)
        return StartJournalChatJobResultBadState(
            type="bad_state",
            detail="failed to find system chat",
        )

    while True:
        ui_entry_raw = await stream.load_next_item(timeout=5)
        if ui_entry_raw.type != "item":
            await stream.cancel()
            stats.incr_failed_to_queue_simple(
                requested_at_unix_date=system_unix_date,
                type=b"reflection_question",
                reason=b"bad_state",
            )
            await stats.stats.store(itgs)
            return StartJournalChatJobResultBadState(
                type="bad_state",
                detail="failed to find journey",
            )

        if (
            ui_entry_raw.item.data.data.type == "ui"
            and ui_entry_raw.item.data.data.conceptually.type == "user_journey"
        ):
            break

    while True:
        extra_entry_raw = await stream.load_next_item(timeout=5)
        if extra_entry_raw.type == "finished":
            break
        if extra_entry_raw.type != "item":
            await stream.cancel()
            stats.incr_failed_to_queue_simple(
                requested_at_unix_date=system_unix_date,
                type=b"reflection_question",
                reason=b"bad_state",
            )
            await stats.stats.store(itgs)
            return StartJournalChatJobResultBadState(
                type="bad_state",
                detail="failed to find end of conversation stream",
            )

        if extra_entry_raw.item.data.data.type != "ui":
            await stream.cancel()
            stats.incr_failed_to_queue_simple(
                requested_at_unix_date=system_unix_date,
                type=b"reflection_question",
                reason=b"bad_state",
            )
            await stats.stats.store(itgs)
            return StartJournalChatJobResultBadState(
                type="bad_state",
                detail="expected all extra trailing items are ui entries",
            )

    journal_master_key = await get_journal_master_key_for_encryption(
        itgs, user_sub=user_sub, now=now
    )
    if journal_master_key.type != "success":
        stats.incr_failed_to_queue_simple(
            requested_at_unix_date=system_unix_date,
            type=b"reflection_question",
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
                type="reflection-question",
                replace_entry_item_uid=None,
                include_previous_history=True,
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
            type=b"reflection_question",
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
            type=b"reflection_question",
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
            type=b"reflection_question",
            reason=b"locked",
        )
        await stats.stats.store(itgs)
        return StartJournalChatJobResultLocked(
            type="locked",
            journal_chat_uid=result.locked_by_journal_chat_uid.decode("utf-8"),
        )

    assert result.type == "succeeded"
    stats.incr_queued(
        requested_at_unix_date=system_unix_date, type=b"reflection_question"
    )
    await stats.stats.store(itgs)
    return AddJournalEntryItemSuccess(
        type="success",
        journal_chat_uid=journal_chat_uid,
    )


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
