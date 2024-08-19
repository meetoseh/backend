import gzip
import time
from typing import Callable, Literal, Protocol, Union, cast

from error_middleware import handle_warning
from itgs import Itgs
from lib.journals.client_keys import get_journal_client_key
from lib.journals.journal_entry_item_data import (
    JournalEntryItemData,
    JournalEntryItemDataDataSummaryV1,
    JournalEntryItemDataDataTextual,
    JournalEntryItemProcessingBlockedReason,
    JournalEntryItemTextualPartParagraph,
)
from lib.journals.master_keys import (
    get_journal_master_key_for_encryption,
    get_journal_master_key_from_s3,
)
from lib.journals.paragraphs import break_paragraphs
from visitors.lib.get_or_create_visitor import VisitorSource
from dataclasses import dataclass
from cryptography.fernet import InvalidToken


@dataclass
class EditEntryItemResultUserNotFound:
    type: Literal["user_not_found"]
    """
    - `user_not_found`: we could not find the indicated user
    """


@dataclass
class EditEntryItemResultEntryNotFound:
    type: Literal["journal_entry_not_found"]
    """
    - `journal_entry_not_found`: the given journal entry does not exist or does not
      belong to the specified user
    """


@dataclass
class EditEntryItemResultItemNotFound:
    type: Literal["journal_entry_item_not_found"]
    """
    - `journal_entry_item_not_found`: there is not a journal entry item with the
      indicated entry counter in the indicated journal entry
    """


@dataclass
class EditEntryItemResultClientKeyRejected:
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
class EditEntryItemResultDecryptExistingError:
    type: Literal["decrypt_existing_error"]
    """
    - `decrypt_existing_error`: we were unable to decrypt the journal entry item
      at the indicated entry counter
    """


@dataclass
class EditEntryItemResultItemBadType:
    type: Literal["journal_entry_item_bad_type"]
    """
    - `journal_entry_item_bad_type`: the journal entry item indicated is not the
      expected type, so it does not make sense to edit its value
    """
    expected: Literal["chat", "reflection-question", "reflection-response", "summary"]
    """The type we expected"""
    actual: Literal[
        "ui", "chat", "reflection-question", "reflection-response", "summary"
    ]
    """The type we got"""


@dataclass
class EditEntryItemResultDecryptNewError:
    type: Literal["decrypt_new_error"]
    """
    - `decrypt_new_error`: the encrypted text payload could not
      be decrypted using the indicated journal client key
    """


@dataclass
class EditEntryItemResultEncryptNewError:
    type: Literal["encrypt_new_error"]
    """
    - `encrypt_new_error`: we could not re-encrypt the payload using the users
      active master encryption key
    """


@dataclass
class EditEntryItemResultStoreRaced:
    type: Literal["store_raced"]
    """
    - `store_raced`: the database row was not updated in the final step,
      probably because one of the referenced fields was mutated while we
      were processing. The database state is the same as it was before,
      so this could be fixed by retrying the operation
    """


@dataclass
class EditEntryItemResultSuccess:
    type: Literal["success"]
    """
    - `success`: the reflection question was successfully edited
    """


EditEntryItemResult = Union[
    EditEntryItemResultUserNotFound,
    EditEntryItemResultEntryNotFound,
    EditEntryItemResultItemNotFound,
    EditEntryItemResultClientKeyRejected,
    EditEntryItemResultDecryptExistingError,
    EditEntryItemResultItemBadType,
    EditEntryItemResultDecryptNewError,
    EditEntryItemResultEncryptNewError,
    EditEntryItemResultStoreRaced,
    EditEntryItemResultSuccess,
]


@dataclass
class EditEntryItemDecryptedTextToItemResultSuccess:
    type: Literal["success"]
    """
    - `success`: the decrypted text was successfully converted to a journal entry item
    """
    data: JournalEntryItemData
    """The data the payload corresponds to"""


EditEntryItemDecryptedTextToItemResult = Union[
    EditEntryItemResultDecryptNewError, EditEntryItemDecryptedTextToItemResultSuccess
]


class EditEntryItemDecryptedTextToItem(Protocol):
    """Describes something capable of taking the decrypted payload and converting it to
    the journal entry item data it is trying to have us save
    """

    async def __call__(
        self, payload: bytes, /, *, error_ctx: Callable[[], str]
    ) -> EditEntryItemDecryptedTextToItemResult:
        """Determines the journal entry item data the decrypted payload corresponds to,
        raising a warning before returning if there is a problem. The warning should be
        prefixed by the result of calling `error_ctx` to provide context for the warning
        (e.g., the user involved)
        """
        ...


class EditEntryItemDecryptedTextToTextualItem:
    def __init__(
        self, type: Literal["chat", "reflection-question", "reflection-response"]
    ):
        self.type: Literal["chat", "reflection-question", "reflection-response"] = type

    async def __call__(
        self, payload: bytes, /, *, error_ctx: Callable[[], str]
    ) -> EditEntryItemDecryptedTextToItemResult:
        try:
            decrypted_text_str = payload.decode("utf-8")
        except UnicodeDecodeError:
            await handle_warning(
                f"{__name__}:decryption_failure",
                f"{error_ctx()} Could not interpret the payload as utf-8",
            )
            return EditEntryItemResultDecryptNewError(type="decrypt_new_error")

        decrypted_text_str = decrypted_text_str.strip()
        if decrypted_text_str == "":
            await handle_warning(
                f"{__name__}:empty_payload",
                f"{error_ctx()}, but the payload was empty",
            )
            return EditEntryItemResultDecryptNewError(type="decrypt_new_error")

        paragraphs = break_paragraphs(decrypted_text_str)

        return EditEntryItemDecryptedTextToItemResultSuccess(
            type="success",
            data=JournalEntryItemData(
                data=JournalEntryItemDataDataTextual(
                    parts=[
                        JournalEntryItemTextualPartParagraph(type="paragraph", value=p)
                        for p in paragraphs
                    ],
                    type="textual",
                ),
                type=self.type,
                processing_block=JournalEntryItemProcessingBlockedReason(
                    reasons=["unchecked"]
                ),
                display_author="other",
            ),
        )


class EditEntryItemDecryptedTextToSummary:
    async def __call__(
        self, payload: bytes, /, *, error_ctx: Callable[[], str]
    ) -> EditEntryItemDecryptedTextToItemResult:
        try:
            result = JournalEntryItemDataDataSummaryV1.model_validate_json(payload)
        except Exception as e:
            await handle_warning(
                f"{__name__}:decryption_failure",
                f"{error_ctx()} Could not interpret the payload as a summary",
                exc=e,
            )
            return EditEntryItemResultDecryptNewError(type="decrypt_new_error")

        return EditEntryItemDecryptedTextToItemResultSuccess(
            type="success",
            data=JournalEntryItemData(
                data=result,
                type="summary",
                processing_block=JournalEntryItemProcessingBlockedReason(
                    reasons=["unchecked"]
                ),
                display_author="other",
            ),
        )


async def edit_entry_item(
    itgs: Itgs,
    /,
    *,
    user_sub: str,
    journal_entry_uid: str,
    entry_counter: int,
    journal_client_key_uid: str,
    platform: VisitorSource,
    encrypted_text: str,
    expected_type: Literal[
        "chat", "reflection-question", "reflection-response", "summary"
    ],
    decrypted_text_to_item: EditEntryItemDecryptedTextToItem,
) -> EditEntryItemResult:
    """Edits the journal entry item within the journal entry with the given uid
    owned by the user with the given sub to the value indicated by the encrypted
    text payload. This will use the journal client key for decrypting and the
    current journal master key of the user for re-encrypting. This will emit a
    warning if appropriate based on the result.

    Args:
        user_sub (str): the sub of the user editing the entry item
        journal_entry_uid (str): the uid of the journal entry to edit
        entry_counter (int): the counter of the item within the entry to edit
        journal_client_key_uid (str): the uid of the journal client key to use
        encrypted_text (str): the encrypted text payload
        expected_type (Literal["chat", "reflection-question", "reflection-response"]): the type of the item to edit
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
        return EditEntryItemResultUserNotFound(type="user_not_found")

    if not response[1].results:
        return EditEntryItemResultEntryNotFound(type="journal_entry_not_found")

    if not response[2].results:
        return EditEntryItemResultItemNotFound(type="journal_entry_item_not_found")

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
        return EditEntryItemResultClientKeyRejected(
            type="client_key_rejected", category="not_found"
        )

    if journal_client_key.type != "success":
        await handle_warning(
            f"{__name__}:key:{journal_client_key.type}",
            f"`{user_sub}` tried to edit a(n) {expected_type}, but we could not retrieve the journal client key: {journal_client_key.type}",
        )
        return EditEntryItemResultClientKeyRejected(
            type="client_key_rejected", category="other"
        )

    if journal_client_key.platform != platform:
        await handle_warning(
            f"{__name__}:key:wrong_platform",
            f"`{user_sub}` tried to edit a(n) {expected_type} using `{journal_client_key_uid}` on `{platform}`, but "
            f"that key is intended for `{journal_client_key.platform}`",
        )
        return EditEntryItemResultClientKeyRejected(
            type="client_key_rejected", category="wrong_platform"
        )

    try:
        decrypted_text_bytes = journal_client_key.journal_client_key.decrypt(
            encrypted_text, ttl=120
        )
    except InvalidToken:
        await handle_warning(
            f"{__name__}:decryption_failure",
            f"User `{user_sub}` tried to edit a(n) {expected_type}, but we could not decrypt the payload",
        )
        return EditEntryItemResultDecryptNewError(type="decrypt_new_error")

    existing_user_journal_master_key = await get_journal_master_key_from_s3(
        itgs,
        user_journal_master_key_uid=existing_user_journal_master_key_uid,
        user_sub=user_sub,
        s3_key=existing_user_journal_master_key_s3_file_key,
    )
    if existing_user_journal_master_key.type != "success":
        await handle_warning(
            f"{__name__}:master_key:{existing_user_journal_master_key.type}",
            f"`{user_sub}` tried to edit a(n) {expected_type}, but we could not retrieve the existing master key: {existing_user_journal_master_key.type}",
        )
        return EditEntryItemResultDecryptExistingError(type="decrypt_existing_error")

    try:
        existing_item_data = JournalEntryItemData.model_validate_json(
            gzip.decompress(
                existing_user_journal_master_key.journal_master_key.decrypt(
                    existing_master_encrypted_data, ttl=None
                )
            )
        )
    except Exception:
        await handle_warning(
            f"{__name__}:decryption_failure",
            f"User `{user_sub}` tried to edit a(n) {expected_type}, but we could not decrypt the existing entry `{journal_entry_uid}`, item `{entry_counter}`",
        )
        return EditEntryItemResultDecryptExistingError(type="decrypt_existing_error")

    if existing_item_data.type != expected_type:
        # since this is probably a client bug, i think its ok to leak the type to slack
        # in order to help fix the bug
        await handle_warning(
            f"{__name__}:bad_type",
            f"User `{user_sub}` tried to edit a `{journal_entry_uid}` item `{entry_counter}`, but that is not a(n) {expected_type} (it is a {existing_item_data.type})",
        )
        return EditEntryItemResultItemBadType(
            type="journal_entry_item_bad_type",
            expected=expected_type,
            actual=existing_item_data.type,
        )

    encryption_master_key = await get_journal_master_key_for_encryption(
        itgs, user_sub=user_sub, now=time.time()
    )
    if encryption_master_key.type == "user_not_found":
        return EditEntryItemResultUserNotFound(type="user_not_found")
    if encryption_master_key.type != "success":
        await handle_warning(
            f"{__name__}:master_key:{encryption_master_key.type}",
            f"`{user_sub}` tried to edit a(n) {expected_type}, but we could not retrieve the encryption master key: {encryption_master_key.type}",
        )
        return EditEntryItemResultEncryptNewError(type="encrypt_new_error")

    parse_payload_result = await decrypted_text_to_item(
        decrypted_text_bytes,
        error_ctx=lambda: f"User `{user_sub}` tried to edit a(n) {expected_type}",
    )
    if parse_payload_result.type != "success":
        return parse_payload_result

    new_encrypted_master_data = encryption_master_key.journal_master_key.encrypt(
        gzip.compress(
            parse_payload_result.data.__pydantic_serializer__.to_json(
                parse_payload_result.data
            ),
            mtime=0,
        )
    ).decode("ascii")

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
            f"User `{user_sub}` tried to edit a(n) {expected_type}, but the database row was not updated",
        )
        return EditEntryItemResultStoreRaced(type="store_raced")

    if response.rows_affected != 1:
        await handle_warning(
            f"{__name__}:store_raced",
            f"User `{user_sub}` tried to edit a(n) {expected_type}, but multiple rows were updated",
            is_urgent=True,
        )
        return EditEntryItemResultStoreRaced(type="store_raced")

    return EditEntryItemResultSuccess(type="success")
