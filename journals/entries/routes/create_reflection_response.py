import gzip
import secrets
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from typing import Annotated, Optional, Literal

from auth import auth_any
from error_middleware import handle_warning
from itgs import Itgs
from journals.entries.routes.sync_journal_entry import (
    ERROR_404_TYPES,
    ERROR_429_TYPES,
    ERROR_JOURNAL_ENTRY_NOT_FOUND_RESPONSE,
    ERROR_KEY_UNAVAILABLE_RESPONSE,
    ERROR_RATELIMITED_RESPONSE,
    SyncJournalEntryResponse,
)
import journals.entry_auth
from lib.journals.client_keys import get_journal_client_key
from lib.journals.conversation_stream import JournalChatJobConversationStream
from lib.journals.journal_entry_item_data import (
    JournalEntryItemData,
    JournalEntryItemDataDataTextual,
    JournalEntryItemProcessingBlockedReason,
    JournalEntryItemTextualPartParagraph,
)
from lib.journals.master_keys import get_journal_master_key_for_encryption
from lib.journals.paragraphs import break_paragraphs
from models import (
    AUTHORIZATION_UNKNOWN_TOKEN,
    STANDARD_ERRORS_BY_CODE,
    StandardErrorResponse,
)
from pydantic import BaseModel, Field
import journals.chat_auth
import lib.journals.start_journal_chat_job
import unix_dates
from users.lib.timezones import get_user_timezone
from visitors.lib.get_or_create_visitor import VisitorSource
import cryptography.fernet


router = APIRouter()


class CreateReflectionResponseRequest(BaseModel):
    platform: VisitorSource = Field(description="the platform the client is running on")
    journal_entry_uid: str = Field(
        description="The UID of the journal entry the user is responding to"
    )
    journal_entry_jwt: str = Field(
        description="The JWT which allows the user to respond to that journal entry"
    )
    journal_client_key_uid: str = Field(
        description=(
            "the UID identifying which journal client key was used to encrypt "
            "the users message"
        )
    )
    encrypted_reflection_response: str = Field(
        description="the Fernet-encrypted reflection response, which is base64url encoded"
    )


ERROR_409_TYPES = Literal["bad_state"]
ERROR_BAD_STATE_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_409_TYPES](
        type="bad_state",
        message="The provided journal entry is not in the correct state for this operation",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=409,
)


@router.post(
    "/reflection/",
    response_model=SyncJournalEntryResponse,
    responses={
        "404": {
            "description": """Further distinguished using `type`:

- `key_unavailable`: the provided journal client key is not available or is not acceptable for this transfer. Generate a new one.
- `journal_entry_not_found`: there is no journal entry with that uid despite valid authorization; it has been deleted.
""",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        "409": {
            "description": "The provided journal entry is not in the correct state for this operation",
            "model": StandardErrorResponse[ERROR_409_TYPES],
        },
        "429": {
            "description": "You have been rate limited. Please try again later. Oseh+ users have less stringent limits",
            "model": StandardErrorResponse[ERROR_429_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def create_reflection_response(
    args: CreateReflectionResponseRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Adds a reflection response to a journal entry, provided it is in an appropriate
    state to accept one (i.e., it has a reflection question without a corresponding
    reflection response). Also flags the journal entry to be included in My Journal.

    Requires standard authorization for the user who owns the given journal entry.
    """
    async with Itgs() as itgs:
        std_auth_result = await auth_any(itgs, authorization)
        if std_auth_result.result is None:
            return std_auth_result.error_response

        entry_auth_result = await journals.entry_auth.auth_any(
            itgs, f"bearer {args.journal_entry_jwt}"
        )
        if entry_auth_result.result is None:
            return entry_auth_result.error_response

        if std_auth_result.result.sub != entry_auth_result.result.user_sub:
            return AUTHORIZATION_UNKNOWN_TOKEN

        if entry_auth_result.result.journal_entry_uid != args.journal_entry_uid:
            return AUTHORIZATION_UNKNOWN_TOKEN

        if entry_auth_result.result.journal_client_key_uid is not None and (
            entry_auth_result.result.journal_client_key_uid
            != args.journal_client_key_uid
        ):
            return AUTHORIZATION_UNKNOWN_TOKEN

        user_tz = await get_user_timezone(itgs, user_sub=std_auth_result.result.sub)
        if user_tz is None:
            return AUTHORIZATION_UNKNOWN_TOKEN

        journal_client_key = await get_journal_client_key(
            itgs,
            user_sub=std_auth_result.result.sub,
            journal_client_key_uid=args.journal_client_key_uid,
            read_consistency="none",
        )
        if journal_client_key.type == "not_found":
            journal_client_key = await get_journal_client_key(
                itgs,
                user_sub=std_auth_result.result.sub,
                journal_client_key_uid=args.journal_client_key_uid,
                read_consistency="weak",
            )
        if journal_client_key.type != "success":
            await handle_warning(
                f"{__name__}:unusable_client_key",
                f"User `{std_auth_result.result.sub}` tried to respond to a journal entry using the journal client "
                f"key `{args.journal_client_key_uid}` for platform `{args.platform}`, but we failed to fetch that "
                f"key: `{journal_client_key.type}`",
            )
            return ERROR_KEY_UNAVAILABLE_RESPONSE
        if journal_client_key.platform != args.platform:
            await handle_warning(
                f"{__name__}:wrong_platform",
                f"User `{std_auth_result.result.sub}` tried to respond to a journal entry using the journal client "
                f"key `{args.journal_client_key_uid}` for platform `{args.platform}`, but that isn't the platform "
                f"that created that key (`{journal_client_key.platform}`).",
            )
            return ERROR_KEY_UNAVAILABLE_RESPONSE

        try:
            reflection_response_bytes = journal_client_key.journal_client_key.decrypt(
                args.encrypted_reflection_response, ttl=120
            )
        except cryptography.fernet.InvalidToken:
            await handle_warning(
                f"{__name__}:invalid_token",
                f"User `{std_auth_result.result.sub}` tried to respond to a journal entry using the journal client "
                f"key `{args.journal_client_key_uid}` for platform `{args.platform}`, but the token failed to decrypt "
                f"their message.",
                is_urgent=True,
            )
            return Response(status_code=500)

        try:
            reflection_response = reflection_response_bytes.decode(
                "utf-8", errors="strict"
            )
        except UnicodeDecodeError as e:
            await handle_warning(
                f"{__name__}:invalid_token",
                f"User `{std_auth_result.result.sub}` tried to respond to a journal entry using the journal client "
                f"key `{args.journal_client_key_uid}` for platform `{args.platform}`, but the decrypted data was "
                f"not valid ({str(e)})",
            )
            return Response(status_code=500)

        journal_master_key = await get_journal_master_key_for_encryption(
            itgs, user_sub=std_auth_result.result.sub, now=time.time()
        )
        if journal_master_key.type != "success":
            await handle_warning(
                f"{__name__}:no_master_key",
                f"User `{std_auth_result.result.sub}` tried to respond to a journal entry with a valid "
                f"request but we could not fetch a journal master key to use: {journal_master_key.type}",
            )
            return Response(
                status_code=503 if journal_master_key.type == "s3_error" else 500
            )

        paragraphs = break_paragraphs(reflection_response)

        if not paragraphs:
            await handle_warning(
                f"{__name__}:no_message",
                f"User `{std_auth_result.result.sub}` tried to respond to a journal entry with a valid "
                f"request but the message was empty after stripping whitespace",
            )
            return Response(status_code=500)

        master_encrypted_data = journal_master_key.journal_master_key.encrypt_at_time(
            gzip.compress(
                JournalEntryItemData.__pydantic_serializer__.to_json(
                    JournalEntryItemData(
                        type="reflection-response",
                        data=JournalEntryItemDataDataTextual(
                            type="textual",
                            parts=[
                                JournalEntryItemTextualPartParagraph(
                                    type="paragraph", value=p
                                )
                                for p in paragraphs
                            ],
                        ),
                        processing_block=JournalEntryItemProcessingBlockedReason(
                            reasons=["unchecked"]
                        ),
                        display_author="self",
                    )
                ),
                mtime=0,
            ),
            int(time.time()),
        ).decode("ascii")

        del paragraphs
        del reflection_response
        del reflection_response_bytes

        stream = JournalChatJobConversationStream(
            journal_entry_uid=args.journal_entry_uid,
            user_sub=std_auth_result.result.sub,
            pending_moderation="ignore",
        )
        await stream.start()

        have_reflection_question = False
        while True:
            next_item = await stream.load_next_item(timeout=5)
            if next_item.type == "timeout":
                await stream.cancel()
                await handle_warning(
                    f"{__name__}:timeout",
                    f"User `{std_auth_result.result.sub}` tried to respond to a journal entry with a valid "
                    f"request but we timed out waiting for the next item in the conversation stream",
                )
                return Response(status_code=503)

            if next_item.type == "finished":
                break

            if next_item.type != "item":
                await stream.cancel()
                await handle_warning(
                    f"{__name__}:bad_stream_item",
                    f"User `{std_auth_result.result.sub}` tried to respond to a journal entry with a valid "
                    f"request but we failed to load the items in their stream: {next_item.type}",
                    exc=next_item.error,
                )
                return Response(status_code=500)

            if next_item.item.data.type == "reflection-question":
                have_reflection_question = True
            elif next_item.item.data.type == "reflection-response":
                have_reflection_question = False

        if not have_reflection_question:
            await handle_warning(
                f"{__name__}:bad_state",
                f"User `{std_auth_result.result.sub}` tried to respond to a journal entry with a valid "
                f"request but the journal entry was not in the correct state to accept a reflection response",
            )
            return ERROR_BAD_STATE_RESPONSE

        conn = await itgs.conn()
        cursor = conn.cursor()

        new_journal_entry_item_uid = f"oseh_jei_{secrets.token_urlsafe(16)}"
        new_journal_entry_item_entry_counter = len(stream.loaded) + 1
        new_journal_entry_item_created_at = time.time()
        new_journal_entry_item_created_unix_date = (
            unix_dates.unix_timestamp_to_unix_date(
                new_journal_entry_item_created_at, tz=user_tz
            )
        )

        del stream

        response = await cursor.executeunified3(
            (
                (  # user_not_found
                    "SELECT 1 FROM users WHERE sub=?",
                    (std_auth_result.result.sub,),
                ),
                (  # journal_entry_not_found
                    """
SELECT 1 FROM journal_entries, users
WHERE
    users.sub = ?
    AND users.id = journal_entries.user_id
    AND journal_entries.uid = ?
                    """,
                    (std_auth_result.result.sub, args.journal_entry_uid),
                ),
                (  # server error
                    """
SELECT 1 FROM user_journal_master_keys, users
WHERE
    users.sub = ?
    AND users.id = user_journal_master_keys.user_id
    AND user_journal_master_keys.uid = ?
                    """,
                    (
                        std_auth_result.result.sub,
                        journal_master_key.journal_master_key_uid,
                    ),
                ),
                (  # bad_state
                    """
SELECT 1 FROM journal_entries, users
WHERE
    users.sub = ?
    AND users.id = journal_entries.user_id
    AND journal_entries.uid = ?
    AND ? = (
        SELECT COUNT(*) FROM journal_entry_items
        WHERE
            journal_entry_items.journal_entry_id = journal_entries.id
    )
    AND NOT EXISTS (
        SELECT 1 FROM journal_entry_items
        WHERE
            journal_entry_items.journal_entry_id = journal_entries.id
            AND journal_entry_items.entry_counter >= ?
    )
                    """,
                    (
                        std_auth_result.result.sub,
                        args.journal_entry_uid,
                        new_journal_entry_item_entry_counter - 1,
                        new_journal_entry_item_entry_counter,
                    ),
                ),
                (  # insert
                    """
INSERT INTO journal_entry_items (
    uid, 
    journal_entry_id, 
    entry_counter, 
    user_journal_master_key_id,
    master_encrypted_data,
    created_at,
    created_unix_date
)
SELECT
    ?,
    journal_entries.id,
    ?,
    user_journal_master_keys.id,
    ?,
    ?,
    ?
FROM users, journal_entries, user_journal_master_keys
WHERE
    users.sub = ?
    AND users.id = journal_entries.user_id
    AND journal_entries.uid = ?
    AND user_journal_master_keys.uid = ?
    AND user_journal_master_keys.user_id = users.id
    AND ? = (
        SELECT COUNT(*) FROM journal_entry_items AS jei
        WHERE
            jei.journal_entry_id = journal_entries.id
    )
    AND NOT EXISTS (
        SELECT 1 FROM journal_entry_items AS jei
        WHERE
            jei.journal_entry_id = journal_entries.id
            AND jei.entry_counter >= ?
    )
                    """,
                    (
                        new_journal_entry_item_uid,
                        new_journal_entry_item_entry_counter,
                        master_encrypted_data,
                        new_journal_entry_item_created_at,
                        new_journal_entry_item_created_unix_date,
                        std_auth_result.result.sub,
                        args.journal_entry_uid,
                        journal_master_key.journal_master_key_uid,
                        new_journal_entry_item_entry_counter - 1,
                        new_journal_entry_item_entry_counter,
                    ),
                ),
                (  # update
                    """
UPDATE journal_entries
SET
  flags = (journal_entries.flags & (~1)),
  canonical_at = ?,
  canonical_unix_date = ?
WHERE
    uid = ?
    AND EXISTS (
        SELECT 1 FROM journal_entry_items
        WHERE journal_entry_items.uid = ? AND journal_entry_items.master_encrypted_data = ?
    )

                    """,
                    (
                        new_journal_entry_item_created_at,
                        new_journal_entry_item_created_unix_date,
                        args.journal_entry_uid,
                        new_journal_entry_item_uid,
                        master_encrypted_data,
                    ),
                ),
            )
        )

        if not response[0].results:
            assert not response[1].results, response
            assert not response[2].results, response
            assert not response[3].results, response
            assert (
                response[4].rows_affected is None or response[4].rows_affected < 1
            ), response
            assert (
                response[5].rows_affected is None or response[5].rows_affected < 1
            ), response
            return AUTHORIZATION_UNKNOWN_TOKEN

        if not response[1].results:
            assert not response[2].results, response
            assert (
                response[4].rows_affected is None or response[4].rows_affected < 1
            ), response
            assert (
                response[5].rows_affected is None or response[5].rows_affected < 1
            ), response
            return ERROR_JOURNAL_ENTRY_NOT_FOUND_RESPONSE

        if not response[2].results:
            assert (
                response[4].rows_affected is None or response[4].rows_affected < 1
            ), response
            assert (
                response[5].rows_affected is None or response[5].rows_affected < 1
            ), response
            await handle_warning(
                f"{__name__}:no_master_key",
                f"User `{std_auth_result.result.sub}` tried to respond to a journal entry with a valid "
                f"request but the journal master key we wanted to use did not have metadata in the database",
            )
            return Response(status_code=500)

        if not response[3].results:
            assert (
                response[4].rows_affected is None or response[4].rows_affected < 1
            ), response
            assert (
                response[5].rows_affected is None or response[5].rows_affected < 1
            ), response
            return ERROR_BAD_STATE_RESPONSE

        if response[4].rows_affected is None or response[4].rows_affected < 1:
            assert (
                response[5].rows_affected is None or response[5].rows_affected < 1
            ), response
            await handle_warning(
                f"{__name__}:no_insert",
                f"User `{std_auth_result.result.sub}` tried to respond to a journal entry with a valid "
                f"request but the insert failed",
            )
            return Response(status_code=500)

        assert response[4].rows_affected == 1, response
        assert response[5].rows_affected == 1, response

        queue_job_at = time.time()
        queue_job_result = await lib.journals.start_journal_chat_job.sync_journal_entry(
            itgs,
            user_sub=std_auth_result.result.sub,
            journal_entry_uid=args.journal_entry_uid,
            now=queue_job_at,
        )
        if queue_job_result.type != "success":
            await handle_warning(
                f"{__name__}:queue_job_failed:{queue_job_result.type}",
                f"User `{std_auth_result.result.sub}` responded to a journal entry successfully, "
                f"but we failed to queue the job to form a response: `{queue_job_result.type}`",
            )

            if queue_job_result.type == "ratelimited":
                return ERROR_RATELIMITED_RESPONSE
            if queue_job_result.type == "user_not_found":
                return AUTHORIZATION_UNKNOWN_TOKEN
            return Response(status_code=500)

        chat_jwt = await journals.chat_auth.create_jwt(
            itgs,
            user_sub=std_auth_result.result.sub,
            journal_entry_uid=args.journal_entry_uid,
            journal_chat_uid=queue_job_result.journal_chat_uid,
            journal_client_key_uid=args.journal_client_key_uid,
            audience="oseh-journal-chat",
        )
        entry_jwt = await journals.entry_auth.create_jwt(
            itgs,
            journal_entry_uid=args.journal_entry_uid,
            journal_client_key_uid=args.journal_client_key_uid,
            user_sub=std_auth_result.result.sub,
            audience="oseh-journal-entry",
        )
        return Response(
            content=SyncJournalEntryResponse(
                journal_chat_jwt=chat_jwt,
                journal_entry_uid=args.journal_entry_uid,
                journal_entry_jwt=entry_jwt,
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=200,
        )
