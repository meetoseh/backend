import time
from typing import Dict, Optional, cast
from itgs import Itgs
import lib.journals.master_keys

from temp_files import temp_file
import socket


async def up(itgs: Itgs):
    """A bug in conversation stream would cause us to update the master encrypted data
    with a newer master key but not update the journal entry item to indicate it's using
    the new master key.

    This walks every journal entry item and verifies it can be decrypted. If not, it tries
    every journal master key for that user to see if it decrypts the item - if it does,
    we update the database row
    """
    conn = await itgs.conn()
    files = await itgs.files()

    with temp_file(".bak") as backup_file:
        with open(backup_file, "wb") as f:
            await conn.backup(f)

        with open(backup_file, "rb") as f:
            await files.upload(
                f,
                bucket=files.default_bucket,
                key=f"s3_files/backup/database/timely/0259_fix_corrupted_journal_items-pre-{int(time.time())}.bak",
                sync=True,
            )

    cursor = conn.cursor("weak")

    # stats for slack message at the end
    num_checked = 0
    num_good = 0
    num_skipped = 0
    num_fixed = 0
    num_still_bad = 0

    last_journal_entry_item_uid: Optional[str] = None
    master_keys_by_uid: Dict[
        str, lib.journals.master_keys.GetJournalMasterKeyForEncryptionResult
    ] = dict()

    async def _get_master_key(
        user_sub: str, uid: str, s3_key: str
    ) -> lib.journals.master_keys.GetJournalMasterKeyForEncryptionResult:
        res = master_keys_by_uid.get(uid)
        if res is None:
            try:
                res = await lib.journals.master_keys.get_journal_master_key_from_s3(
                    itgs,
                    user_journal_master_key_uid=uid,
                    user_sub=user_sub,
                    s3_key=s3_key,
                )
            except Exception as e:
                res = lib.journals.master_keys.GetJournalMasterKeyForEncryptionResultS3Error(
                    type="s3_error",
                    user_sub=user_sub,
                    journal_master_key_uid=uid,
                    exc=e,
                )
            master_keys_by_uid[uid] = res
        return res

    while True:
        response = await cursor.execute(
            """
SELECT
    journal_entry_items.uid,
    users.sub,
    user_journal_master_keys.uid,
    s3_files.key,
    journal_entry_items.master_encrypted_data
FROM journal_entry_items, journal_entries, users, user_journal_master_keys, s3_files
WHERE
    (? IS NULL OR journal_entry_items.uid > ?)
    AND journal_entries.id = journal_entry_items.journal_entry_id
    AND users.id = journal_entries.user_id
    AND user_journal_master_keys.id = journal_entry_items.user_journal_master_key_id
    AND user_journal_master_keys.user_id = users.id
    AND s3_files.id = user_journal_master_keys.s3_file_id
ORDER BY journal_entry_items.uid ASC
LIMIT 100
            """,
            (last_journal_entry_item_uid, last_journal_entry_item_uid),
        )
        if not response.results:
            break

        last_journal_entry_item_uid = cast(str, response.results[-1][0])

        for row in response.results:
            num_checked += 1
            row_uid = cast(str, row[0])
            row_user_sub = cast(str, row[1])
            row_master_key_uid = cast(str, row[2])
            row_master_key_s3_key = cast(str, row[3])
            row_master_encrypted_data = cast(bytes, row[4])

            row_master_key = await _get_master_key(
                row_user_sub, row_master_key_uid, row_master_key_s3_key
            )

            if row_master_key.type != "success":
                num_skipped += 1
                continue

            try:
                row_master_key.journal_master_key.decrypt(row_master_encrypted_data)
                num_good += 1
                continue
            except:
                pass  # fall through

            inner_response = await cursor.execute(
                """
SELECT
    user_journal_master_keys.uid,
    s3_files.key
FROM user_journal_master_keys, users, s3_files
WHERE
    user_journal_master_keys.user_id = users.id
    AND users.sub = ?
    AND user_journal_master_keys.uid != ?
    AND s3_files.id = user_journal_master_keys.s3_file_id
                """,
                (row_user_sub, row_master_key_uid),
            )
            for alternate_key_uid, alternate_key_s3_file in (
                inner_response.results or []
            ):
                alternate_key = await _get_master_key(
                    row_user_sub, alternate_key_uid, alternate_key_s3_file
                )
                if alternate_key.type != "success":
                    continue
                try:
                    alternate_key.journal_master_key.decrypt(row_master_encrypted_data)
                except:
                    continue
                num_fixed += 1
                await cursor.execute(
                    """
UPDATE journal_entry_items
SET user_journal_master_key_id = (
    SELECT user_journal_master_keys.id
    FROM user_journal_master_keys
    WHERE user_journal_master_keys.uid = ?
)
WHERE uid = ?
                    """,
                    (alternate_key_uid, row_uid),
                )
                break
            else:
                num_still_bad += 1

    slack = await itgs.slack()
    await slack.send_ops_message(
        f"{socket.gethostname()} - 0259_fix_corrupted_journal_items:\n\n"
        f"```\n{num_checked=}\n{num_good=}\n{num_skipped=}\n{num_fixed=}\n{num_still_bad=}\n```"
    )

    with temp_file(".bak") as backup_file:
        with open(backup_file, "wb") as f:
            await conn.backup(f)

        with open(backup_file, "rb") as f:
            await files.upload(
                f,
                bucket=files.default_bucket,
                key=f"s3_files/backup/database/timely/0259_fix_corrupted_journal_items-post-{int(time.time())}.bak",
                sync=True,
            )
