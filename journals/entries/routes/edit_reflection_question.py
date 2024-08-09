import asyncio
import gzip
import os
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from typing import Annotated, List, Optional, Literal, Union, cast

from pydantic import BaseModel, Field
from auth import auth_any
from error_middleware import handle_warning
from itgs import Itgs
from journals.entries.routes.sync_journal_entry import (
    ERROR_429_TYPES,
    ERROR_JOURNAL_ENTRY_NOT_FOUND_RESPONSE,
    ERROR_KEY_UNAVAILABLE_RESPONSE,
    ERROR_RATELIMITED_RESPONSE,
    SyncJournalEntryResponse,
)
from lib.journals.client_keys import get_journal_client_key
from lib.journals.journal_entry_item_data import (
    JournalEntryItemData,
    JournalEntryItemDataDataTextual,
    JournalEntryItemTextualPartParagraph,
)
from lib.journals.master_keys import (
    get_journal_master_key_for_encryption,
    get_journal_master_key_from_s3,
)
from models import (
    AUTHORIZATION_UNKNOWN_TOKEN,
    STANDARD_ERRORS_BY_CODE,
    StandardErrorResponse,
)
import journals.chat_auth
import journals.entry_auth
import lib.journals.start_journal_chat_job
import journals.entry_auth
from visitors.lib.get_or_create_visitor import VisitorSource
from dataclasses import dataclass
from cryptography.fernet import InvalidToken
import openai


class EditReflectionQuestionRequest(BaseModel):
    platform: VisitorSource = Field(description="the platform the client is running on")
    journal_client_key_uid: str = Field(
        description=(
            "the UID identifying which journal client key to use an "
            "additional layer of encryption"
        )
    )
    journal_entry_uid: str = Field(
        description="the UID of the journal entry that was created"
    )
    journal_entry_jwt: str = Field(
        description="a JWT that allows the user to respond to the journal entry"
    )
    entry_counter: int = Field(
        description="The entry counter of the item within the journal to edit"
    )
    encrypted_reflection_question: str = Field(
        description="The new value of the reflection question, encrypted with the client key"
    )


router = APIRouter()


ERROR_404_TYPES = Literal[
    "key_unavailable", "journal_entry_not_found", "journal_entry_item_not_found"
]

ERROR_409_TYPES = Literal["bad_state"]
ERROR_BAD_STATE_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_409_TYPES](
        type="bad_state",
        message="The provided journal entry is not in the correct state for this operation",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=409,
)

ERROR_500_TYPES = Literal["contact_support"]


@router.post(
    "/edit_reflection_question",
    response_model=SyncJournalEntryResponse,
    responses={
        "404": {
            "description": """Further distinguished using `type`:

- `key_unavailable`: the provided journal client key is not available or is not acceptable for this transfer. Generate a new one.
- `journal_entry_not_found`: there is no journal entry with that uid despite valid authorization; it has been deleted.
- `journal_entry_item_not_found`: the journal entry exists, but either the entry indicated doesn't exist,
  or isn't a reflection question
""",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        "429": {
            "description": "You have been rate limited. Please try again later. Oseh+ users have less stringent limits",
            "model": StandardErrorResponse[ERROR_429_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def edit_reflection_question(
    args: EditReflectionQuestionRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Edits the indicated reflection question and returns the JWT required to stream
    the new state of the entry. The client MAY skip streaming the entry and instead choose
    to update the entry client-side after a successful response, but only if they are careful
    to trim the reflection question and break paragraphs.

    Requires standard authorization for the user that the journal entry belongs to,
    plus an additional JWT authorizing viewing that journal entry.
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

        if entry_auth_result.result.journal_entry_uid != args.journal_entry_uid:
            return AUTHORIZATION_UNKNOWN_TOKEN

        if entry_auth_result.result.user_sub != std_auth_result.result.sub:
            await handle_warning(
                f"{__name__}:stolen_jwt",
                f"User {std_auth_result.result.sub} tried to sync + ensure a reflection question, but the JWT provided "
                f"was for a different user ({entry_auth_result.result.user_sub})",
                is_urgent=True,
            )
            return AUTHORIZATION_UNKNOWN_TOKEN

        edit_result = await edit_entry_reflection_question(
            itgs,
            user_sub=std_auth_result.result.sub,
            journal_entry_uid=args.journal_entry_uid,
            entry_counter=args.entry_counter,
            journal_client_key_uid=args.journal_client_key_uid,
            platform=args.platform,
            encrypted_reflection_question=args.encrypted_reflection_question,
        )
        if edit_result.type == "user_not_found":
            return AUTHORIZATION_UNKNOWN_TOKEN
        if edit_result.type == "journal_entry_not_found":
            return ERROR_JOURNAL_ENTRY_NOT_FOUND_RESPONSE
        if edit_result.type == "journal_entry_item_not_found":
            return Response(
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="journal_entry_item_not_found",
                    message="The provided journal entry item does not exist",
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=404,
            )
        if edit_result.type == "client_key_rejected":
            return ERROR_KEY_UNAVAILABLE_RESPONSE
        if edit_result.type == "journal_entry_item_bad_type":
            return ERROR_BAD_STATE_RESPONSE
        if edit_result.type != "success":
            return Response(
                content=StandardErrorResponse[ERROR_500_TYPES](
                    type="contact_support",
                    message="An internal error occurred. Please contact support.",
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=500,
            )

        queue_job_at = time.time()
        queue_job_result = await lib.journals.start_journal_chat_job.sync_journal_entry(
            itgs,
            journal_entry_uid=args.journal_entry_uid,
            user_sub=std_auth_result.result.sub,
            now=queue_job_at,
        )

        if queue_job_result.type != "success" and queue_job_result.type != "locked":
            await handle_warning(
                f"{__name__}:queue_job_failed:{queue_job_result.type}",
                f"User `{std_auth_result.result.sub}` tried to retrieve a journal entry, but we failed to queue the job",
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
        return Response(
            content=SyncJournalEntryResponse(
                journal_chat_jwt=chat_jwt,
                journal_entry_uid=args.journal_entry_uid,
                journal_entry_jwt=args.journal_entry_jwt,
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=200,
        )


@dataclass
class EditEntryReflectionQuestionResultUserNotFound:
    type: Literal["user_not_found"]
    """
    - `user_not_found`: we could not find the indicated user
    """


@dataclass
class EditEntryReflectionQuestionResultEntryNotFound:
    type: Literal["journal_entry_not_found"]
    """
    - `journal_entry_not_found`: the given journal entry does not exist or does not
      belong to the specified user
    """


@dataclass
class EditEntryReflectionQuestionResultItemNotFound:
    type: Literal["journal_entry_item_not_found"]
    """
    - `journal_entry_item_not_found`: there is not a journal entry item with the
      indicated entry counter in the indicated journal entry
    """


@dataclass
class EditEntryReflectionQuestionResultClientKeyRejected:
    type: Literal["client_key_rejected"]
    """
    - `client_key_rejected`: we are unable or unwilling to use the specified journal
       client key for this operation
    """
    category: Literal["not_found", "wrong_platform", "other"]
    """
    - `not_found`: the journal client key does not exist
    - `wrong_platform`: the journal client key was not created for the indicated platform
    - `other`: some other reason we are rejecting the key
    """


@dataclass
class EditEntryReflectionQuestionResultDecryptExistingError:
    type: Literal["decrypt_existing_error"]
    """
    - `decrypt_existing_error`: we were unable to decrypt the journal entry item
      at the indicated entry counter
    """


@dataclass
class EditEntryReflectionQuestionItemBadType:
    type: Literal["journal_entry_item_bad_type"]
    """
    - `journal_entry_item_bad_type`: the journal entry item indicated is not a reflection
      question, so it does not make sense to edit its value using this endpoint
    """
    expected: Literal["reflection-question"]
    """The type we expected"""
    actual: str
    """The type we got"""


@dataclass
class EditEntryReflectionQuestionResultDecryptNewError:
    type: Literal["decrypt_new_error"]
    """
    - `decrypt_new_error`: the encrypted reflection question payload could not
      be decrypted using the indicated journal client key
    """


@dataclass
class EditEntryReflectionQuestionResultEncryptNewError:
    type: Literal["encrypt_new_error"]
    """
    - `encrypt_new_error`: we could not re-encrypt the payload using the users
      active master encryption key
    """


@dataclass
class EditEntryReflectionQuestionResultFlagged:
    type: Literal["flagged"]
    """
    - `flagged`: the reflection question was flagged by OpenAI's moderation service
    """


@dataclass
class EditEntryReflectionQuestionResultStoreRaced:
    type: Literal["store_raced"]
    """
    - `store_raced`: the database row was not updated in the final step,
      probably because one of the referenced fields was mutated while we
      were processing. The database state is the same as it was before,
      so this could be fixed by retrying the operation
    """


@dataclass
class EditEntryReflectionQuestionResultSuccess:
    type: Literal["success"]
    """
    - `success`: the reflection question was successfully edited
    """


EditEntryReflectionQuestionResult = Union[
    EditEntryReflectionQuestionResultUserNotFound,
    EditEntryReflectionQuestionResultEntryNotFound,
    EditEntryReflectionQuestionResultItemNotFound,
    EditEntryReflectionQuestionResultClientKeyRejected,
    EditEntryReflectionQuestionResultDecryptExistingError,
    EditEntryReflectionQuestionItemBadType,
    EditEntryReflectionQuestionResultDecryptNewError,
    EditEntryReflectionQuestionResultEncryptNewError,
    EditEntryReflectionQuestionResultFlagged,
    EditEntryReflectionQuestionResultStoreRaced,
    EditEntryReflectionQuestionResultSuccess,
]


async def edit_entry_reflection_question(
    itgs: Itgs,
    /,
    *,
    user_sub: str,
    journal_entry_uid: str,
    entry_counter: int,
    journal_client_key_uid: str,
    platform: VisitorSource,
    encrypted_reflection_question: str,
) -> EditEntryReflectionQuestionResult:
    """Edits the reflection question within the journal entry with the given uid
    owned by the user with the given sub to the value indicated by the encrypted
    reflection question payload. This will use the journal client key for decrypting
    and the current journal master key of the user for re-encrypting. This will
    emit a warning if appropriate based on the result.

    Args:
        user_sub (str): the sub of the user editing the reflection question
        journal_entry_uid (str): the uid of the journal entry to edit
        entry_counter (int): the counter of the item within the entry to edit
        journal_client_key_uid (str): the uid of the journal client key to use
        encrypted_reflection_question (str): the encrypted reflection question payload
    """

    conn = await itgs.conn()
    cursor = conn.cursor()
    response = await cursor.executeunified3(
        (
            (
                "SELECT 1 FROM users WHERE sub=?",
                (user_sub,),
            ),
            (
                """
SELECT 1 
FROM users, journal_entries
WHERE 
    users.sub = ?
    AND journal_entries.user_id = users.id
    AND journal_entries.uid = ? 
                """,
                (user_sub, journal_entry_uid),
            ),
            (
                """
SELECT
    user_journal_master_keys.uid,
    s3_files.key,
    journal_entry_items.master_encrypted_data
FROM users, journal_entries, journal_entry_items, user_journal_master_keys, s3_files
WHERE
    users.sub = ?
    AND journal_entries.user_id = users.id
    AND journal_entries.uid = ?
    AND journal_entry_items.journal_entry_id = journal_entries.id
    AND journal_entry_items.entry_counter = ?
    AND user_journal_master_keys.user_id = users.id
    AND user_journal_master_keys.id = journal_entry_items.user_journal_master_key_id
    AND s3_files.id = user_journal_master_keys.s3_file_id
                """,
                (user_sub, journal_entry_uid, entry_counter),
            ),
        )
    )
    if not response[0].results:
        return EditEntryReflectionQuestionResultUserNotFound(type="user_not_found")

    if not response[1].results:
        return EditEntryReflectionQuestionResultEntryNotFound(
            type="journal_entry_not_found"
        )

    if not response[2].results:
        return EditEntryReflectionQuestionResultItemNotFound(
            type="journal_entry_item_not_found"
        )

    assert len(response[2].results) == 1, response

    existing_user_journal_master_key_uid = cast(str, response[2].results[0][0])
    existing_user_journal_master_key_s3_file_key = cast(str, response[2].results[0][1])
    existing_master_encrypted_data = cast(str, response[2].results[0][2])

    journal_client_key = await get_journal_client_key(
        itgs,
        user_sub=user_sub,
        journal_client_key_uid=journal_client_key_uid,
        read_consistency="none",
    )
    if journal_client_key.type == "not_found":
        journal_client_key = await get_journal_client_key(
            itgs,
            user_sub=user_sub,
            journal_client_key_uid=journal_client_key_uid,
            read_consistency="weak",
        )

    if journal_client_key.type == "not_found":
        return EditEntryReflectionQuestionResultClientKeyRejected(
            type="client_key_rejected", category="not_found"
        )

    if journal_client_key.type != "success":
        await handle_warning(
            f"{__name__}:key:{journal_client_key.type}",
            f"`{user_sub}` tried to edit a reflection question, but we could not retrieve the journal client key: {journal_client_key.type}",
        )
        return EditEntryReflectionQuestionResultClientKeyRejected(
            type="client_key_rejected", category="other"
        )

    if journal_client_key.platform != platform:
        await handle_warning(
            f"{__name__}:key:wrong_platform",
            f"`{user_sub}` tried to edit a reflection question using `{journal_client_key_uid}` on `{platform}`, but "
            f"that key is intended for `{journal_client_key.platform}`",
        )
        return EditEntryReflectionQuestionResultClientKeyRejected(
            type="client_key_rejected", category="wrong_platform"
        )

    try:
        decrypted_reflection_question_bytes = (
            journal_client_key.journal_client_key.decrypt(
                encrypted_reflection_question, ttl=120
            )
        )
    except InvalidToken:
        await handle_warning(
            f"{__name__}:decryption_failure",
            f"User `{user_sub}` tried to edit a reflection question, but we could not decrypt the payload",
        )
        return EditEntryReflectionQuestionResultDecryptNewError(
            type="decrypt_new_error"
        )

    try:
        decrypted_reflection_question_str = decrypted_reflection_question_bytes.decode(
            "utf-8"
        )
    except UnicodeDecodeError:
        await handle_warning(
            f"{__name__}:decryption_failure",
            f"User `{user_sub}` tried to edit a reflection question, but we could not decode the payload",
        )
        return EditEntryReflectionQuestionResultDecryptNewError(
            type="decrypt_new_error"
        )

    decrypted_reflection_question_str = decrypted_reflection_question_str.strip()
    if decrypted_reflection_question_str == "":
        await handle_warning(
            f"{__name__}:empty_payload",
            f"User `{user_sub}` tried to edit a reflection question, but the payload was empty",
        )
        return EditEntryReflectionQuestionResultDecryptNewError(
            type="decrypt_new_error"
        )

    client = openai.OpenAI(api_key=os.environ["OSEH_OPENAI_API_KEY"])
    moderation_response_task = asyncio.create_task(
        asyncio.to_thread(
            client.moderations.create, input=decrypted_reflection_question_str
        )
    )

    existing_user_journal_master_key = await get_journal_master_key_from_s3(
        itgs,
        user_journal_master_key_uid=existing_user_journal_master_key_uid,
        user_sub=user_sub,
        s3_key=existing_user_journal_master_key_s3_file_key,
    )
    if existing_user_journal_master_key.type != "success":
        moderation_response_task.cancel()
        await handle_warning(
            f"{__name__}:master_key:{existing_user_journal_master_key.type}",
            f"`{user_sub}` tried to edit a reflection question, but we could not retrieve the existing master key: {existing_user_journal_master_key.type}",
        )
        return EditEntryReflectionQuestionResultDecryptExistingError(
            type="decrypt_existing_error"
        )

    try:
        existing_item_data = JournalEntryItemData.model_validate_json(
            gzip.decompress(
                existing_user_journal_master_key.journal_master_key.decrypt(
                    existing_master_encrypted_data, ttl=None
                )
            )
        )
    except Exception:
        moderation_response_task.cancel()
        await handle_warning(
            f"{__name__}:decryption_failure",
            f"User `{user_sub}` tried to edit a reflection question, but we could not decrypt the existing entry `{journal_entry_uid}`, item `{entry_counter}`",
        )
        return EditEntryReflectionQuestionResultDecryptExistingError(
            type="decrypt_existing_error"
        )

    if existing_item_data.type != "reflection-question":
        moderation_response_task.cancel()
        # since this is probably a client bug, i think its ok to leak the type to slack
        # in order to help fix the bug
        await handle_warning(
            f"{__name__}:bad_type",
            f"User `{user_sub}` tried to edit a `{journal_entry_uid}` item `{entry_counter}`, but that is not a reflection question (it is a {existing_item_data.type})",
        )
        return EditEntryReflectionQuestionItemBadType(
            type="journal_entry_item_bad_type",
            expected="reflection-question",
            actual=existing_item_data.type,
        )

    paragraphs = break_paragraphs(decrypted_reflection_question_str)
    if (
        existing_item_data.data.type == "textual"
        and len(paragraphs) == len(existing_item_data.data.parts)
        and all(
            p.type == "paragraph" and p.value == paragraphs[i]
            for i, p in enumerate(existing_item_data.data.parts)
        )
    ):
        moderation_response_task.cancel()
        await handle_warning(
            f"{__name__}:no_change",
            f"User `{user_sub}` tried to edit a reflection question, but the new value is the same as the old value. The client should skip the api request",
        )
        return EditEntryReflectionQuestionResultSuccess(type="success")

    new_item_data = JournalEntryItemData(
        data=JournalEntryItemDataDataTextual(
            parts=[
                JournalEntryItemTextualPartParagraph(type="paragraph", value=p)
                for p in paragraphs
            ],
            type="textual",
        ),
        type="reflection-question",
        display_author="other",
    )

    encryption_master_key = await get_journal_master_key_for_encryption(
        itgs, user_sub=user_sub, now=time.time()
    )
    if encryption_master_key.type == "user_not_found":
        moderation_response_task.cancel()
        return EditEntryReflectionQuestionResultUserNotFound(type="user_not_found")
    if encryption_master_key.type != "success":
        moderation_response_task.cancel()
        await handle_warning(
            f"{__name__}:master_key:{encryption_master_key.type}",
            f"`{user_sub}` tried to edit a reflection question, but we could not retrieve the encryption master key: {encryption_master_key.type}",
        )
        return EditEntryReflectionQuestionResultEncryptNewError(
            type="encrypt_new_error"
        )

    new_encrypted_master_data = encryption_master_key.journal_master_key.encrypt(
        gzip.compress(new_item_data.__pydantic_serializer__.to_json(new_item_data))
    ).decode("ascii")

    moderation_response = await moderation_response_task
    if moderation_response.results[0].flagged:
        await handle_warning(
            f"{__name__}:moderation",
            f"User `{user_sub}` tried to edit a reflection question, but the payload was flagged by OpenAI's moderation service",
        )
        return EditEntryReflectionQuestionResultFlagged(type="flagged")

    response = await cursor.execute(
        """
UPDATE journal_entry_items 
SET master_encrypted_data=?, user_journal_master_key_id=(
  SELECT user_journal_master_keys.id
  FROM users, user_journal_master_keys
  WHERE
    users.sub = ?
    AND user_journal_master_keys.user_id = users.id
    AND user_journal_master_keys.uid = ?
)
WHERE
    journal_entry_items.journal_entry_id = (
        SELECT journal_entries.id
        FROM users, journal_entries
        WHERE
            users.sub = ?
            AND journal_entries.user_id = users.id
            AND journal_entries.uid = ?
    )
    AND journal_entry_items.entry_counter = ?
    AND journal_entry_items.master_encrypted_data = ?
        """,
        (
            new_encrypted_master_data,
            user_sub,
            encryption_master_key.journal_master_key_uid,
            user_sub,
            journal_entry_uid,
            entry_counter,
            existing_master_encrypted_data,
        ),
    )
    if response.rows_affected is None or response.rows_affected < 1:
        await handle_warning(
            f"{__name__}:store_raced",
            f"User `{user_sub}` tried to edit a reflection question, but the database row was not updated",
        )
        return EditEntryReflectionQuestionResultStoreRaced(type="store_raced")

    if response.rows_affected != 1:
        await handle_warning(
            f"{__name__}:store_raced",
            f"User `{user_sub}` tried to edit a reflection question, but multiple rows were updated",
            is_urgent=True,
        )
        return EditEntryReflectionQuestionResultStoreRaced(type="store_raced")

    return EditEntryReflectionQuestionResultSuccess(type="success")


def break_paragraphs(text: str) -> List[str]:
    """Breaks the given text into paragraphs, removing empty lines and leading/trailing whitespace"""
    result = [p.strip() for p in text.split("\n")]
    return [p for p in result if p]
