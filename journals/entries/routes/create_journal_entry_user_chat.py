import gzip
import secrets
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from typing import Annotated, Optional, Literal
from auth import auth_any
from error_middleware import handle_warning
from itgs import Itgs
import journals.entry_auth
from lib.journals.client_keys import get_journal_client_key
from lib.journals.journal_entry_item_data import (
    JournalEntryItemData,
    JournalEntryItemDataDataTextual,
    JournalEntryItemTextualPartParagraph,
)
from lib.journals.master_keys import get_journal_master_key_for_encryption
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


class CreateJournalEntryUserChatRequest(BaseModel):
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
    encrypted_user_message: str = Field(
        description="the Fernet-encrypted user message, which is base64url encoded"
    )


class CreateJournalEntryUserChatResponse(BaseModel):
    journal_chat_jwt: str = Field(
        description=(
            "the JWT to provide to the websocket endpoint /api/2/journals/chat to "
            "retrieve the systems response"
        )
    )
    journal_entry_uid: str = Field(
        description="the same journal entry UID that was provided, for consistency of response format with the greeting endpoint"
    )
    journal_entry_jwt: str = Field(
        description="a new, refreshed JWT that allows the user to respond to the journal entry"
    )


ERROR_400_TYPES = Literal["bad_encryption"]
ERROR_BAD_ENCRYPTION = Response(
    content=StandardErrorResponse[ERROR_400_TYPES](
        type="bad_encryption",
        message="The provided encrypted message was invalid",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=400,
)


ERROR_404_TYPES = Literal["key_unavailable", "journal_entry_not_found"]
ERROR_KEY_UNAVAILABLE_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="key_unavailable",
        message="The provided journal client key is not available or is not acceptable for this transfer. Generate a new one.",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=404,
)
ERROR_JOURNAL_ENTRY_NOT_FOUND = Response(
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="journal_entry_not_found",
        message="The provided journal entry was not found",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=404,
)


ERROR_409_TYPES = Literal["journal_entry_bad_state"]
ERROR_JOURNAL_ENTRY_BAD_STATE = Response(
    content=StandardErrorResponse[ERROR_409_TYPES](
        type="journal_entry_bad_state",
        message="The provided journal entry is not in the correct state for this operation",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=409,
)

ERROR_429_TYPES = Literal["system_response_ratelimited"]
ERROR_RATELIMITED_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_429_TYPES](
        type="system_response_ratelimited",
        message="You have been rate limited. Your response has been stored, but no system message is coming. Please try again later. Oseh+ users have less stringent limits",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=429,
)


@router.post(
    "/chat/",
    response_model=CreateJournalEntryUserChatResponse,
    responses={
        "404": {
            "model": StandardErrorResponse[ERROR_404_TYPES],
            "description": "Either the provided journal client key is not available or is not acceptable for this transfer, or the journal entry could not be found.",
        },
        "409": {
            "model": StandardErrorResponse[ERROR_409_TYPES],
            "description": "The provided journal entry is not in the correct state for this operation",
        },
        "429": {
            "model": StandardErrorResponse[ERROR_429_TYPES],
            "description": (
                "The user has been rate limited. The response has been stored, "
                "but no system message is coming. Oseh+ users have less stringent limits.\n\n"
                "You should wait a bit and use POST /api/1/journals/chat/retry_system_response to try and "
                "get a response from the system"
            ),
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def create_journal_entry_user_chat(
    args: CreateJournalEntryUserChatRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Adds a new user message to the journal entry with the indicated uid,
    as authorized by the given JWT, so long as the journal entry is in the
    correct state for the operation (i.e., the last message was a greeting
    from the system).

    The client must connect over TLS as well as encrypt the message with a
    journal client key, whose UID is indicated in the request (see the
    greeting endpoint for the motivation)

    Requires standard authorization for the same user as in the journal entry
    JWT to prevent indirectly extending user JWTs via journal entry JWTs.
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
            user_message_bytes = journal_client_key.journal_client_key.decrypt(
                args.encrypted_user_message, ttl=120
            )
        except cryptography.fernet.InvalidToken:
            is_ttl_issue = False
            try:
                journal_client_key.journal_client_key.decrypt(
                    args.encrypted_user_message
                )
                is_ttl_issue = True
            except cryptography.fernet.InvalidToken:
                pass
            await handle_warning(
                f"{__name__}:invalid_token",
                f"User `{std_auth_result.result.sub}` tried to respond to a journal entry using the journal client "
                f"key `{args.journal_client_key_uid}` for platform `{args.platform}`, but the token failed to decrypt "
                f"their message. `{is_ttl_issue=}`",
            )
            return ERROR_BAD_ENCRYPTION

        try:
            user_message = user_message_bytes.decode("utf-8", errors="strict")
        except UnicodeDecodeError as e:
            await handle_warning(
                f"{__name__}:invalid_token",
                f"User `{std_auth_result.result.sub}` tried to respond to a journal entry using the journal client "
                f"key `{args.journal_client_key_uid}` for platform `{args.platform}`, but the decrypted data was "
                f"not valid ({str(e)})",
            )
            return ERROR_BAD_ENCRYPTION

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

        paragraphs = [p.strip() for p in user_message.split("\n")]
        paragraphs = [p for p in paragraphs if p]

        if not paragraphs:
            await handle_warning(
                f"{__name__}:no_message",
                f"User `{std_auth_result.result.sub}` tried to respond to a journal entry with a valid "
                f"request but the message was empty after stripping whitespace",
            )
            return ERROR_BAD_ENCRYPTION

        master_encrypted_data = journal_master_key.journal_master_key.encrypt_at_time(
            gzip.compress(
                JournalEntryItemData.__pydantic_serializer__.to_json(
                    JournalEntryItemData(
                        type="chat",
                        data=JournalEntryItemDataDataTextual(
                            type="textual",
                            parts=[
                                JournalEntryItemTextualPartParagraph(
                                    type="paragraph", value=p
                                )
                                for p in paragraphs
                            ],
                        ),
                        display_author="self",
                    )
                ),
                mtime=0,
            ),
            int(time.time()),
        ).decode("ascii")
        del user_message_bytes
        del user_message
        del paragraphs

        conn = await itgs.conn()
        cursor = conn.cursor()

        new_journal_entry_item_uid = f"oseh_jei_{secrets.token_urlsafe(16)}"
        new_journal_entry_created_at = time.time()
        new_journal_entry_created_unix_date = unix_dates.unix_timestamp_to_unix_date(
            new_journal_entry_created_at, tz=user_tz
        )
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
    AND 1 = (
        SELECT COUNT(*) FROM journal_entry_items
        WHERE
            journal_entry_items.journal_entry_id = journal_entries.id
    )
                    """,
                    (std_auth_result.result.sub, args.journal_entry_uid),
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
    1 + (
        SELECT 
            MAX(jei.entry_counter) 
        FROM journal_entry_items AS jei
        WHERE 
            jei.journal_entry_id = journal_entries.id
    ),
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
    AND 1 = (
        SELECT COUNT(*) FROM journal_entry_items AS jei
        WHERE
            jei.journal_entry_id = journal_entries.id
    )
                    """,
                    (
                        new_journal_entry_item_uid,
                        master_encrypted_data,
                        new_journal_entry_created_at,
                        new_journal_entry_created_unix_date,
                        std_auth_result.result.sub,
                        args.journal_entry_uid,
                        journal_master_key.journal_master_key_uid,
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
            return AUTHORIZATION_UNKNOWN_TOKEN

        if not response[1].results:
            assert not response[2].results, response
            assert (
                response[4].rows_affected is None or response[4].rows_affected < 1
            ), response
            return ERROR_JOURNAL_ENTRY_NOT_FOUND

        if not response[2].results:
            assert (
                response[4].rows_affected is None or response[4].rows_affected < 1
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
            return ERROR_JOURNAL_ENTRY_BAD_STATE

        if response[4].rows_affected is None or response[4].rows_affected < 1:
            await handle_warning(
                f"{__name__}:no_insert",
                f"User `{std_auth_result.result.sub}` tried to respond to a journal entry with a valid "
                f"request but the insert failed",
            )
            return Response(status_code=500)

        queue_job_at = time.time()
        queue_job_result = (
            await lib.journals.start_journal_chat_job.add_journal_entry_chat(
                itgs,
                user_sub=std_auth_result.result.sub,
                journal_entry_uid=args.journal_entry_uid,
                now=queue_job_at,
            )
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
            content=CreateJournalEntryUserChatResponse(
                journal_chat_jwt=chat_jwt,
                journal_entry_uid=args.journal_entry_uid,
                journal_entry_jwt=entry_jwt,
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=200,
        )
