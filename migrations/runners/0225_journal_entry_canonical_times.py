from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()
    await cursor.executemany2(
        (
            "PRAGMA foreign_keys=off",
            "DROP INDEX journal_entries_user_id_index",
            """
CREATE TABLE journal_entries_new (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    flags INTEGER NOT NULL,
    created_at REAL NOT NULL,
    created_unix_date INTEGER NOT NULL,
    canonical_at REAL NOT NULL,
    canonical_unix_date INTEGER NOT NULL
)
            """,
            """
WITH journal_entry_last_item_times(journal_entry_id, last_item_created_at, last_item_created_unix_date) AS (
SELECT
    journal_entries.id,
    MAX(journal_entry_items.created_at),
    MAX(journal_entry_items.created_unix_date)
FROM journal_entries, journal_entry_items
WHERE journal_entries.id = journal_entry_items.journal_entry_id
GROUP BY journal_entries.id
)
INSERT INTO journal_entries_new (
    id, uid, user_id, flags, created_at, created_unix_date, canonical_at, canonical_unix_date
)
SELECT
    journal_entries.id,
    journal_entries.uid,
    journal_entries.user_id,
    journal_entries.flags,
    journal_entries.created_at,
    journal_entries.created_unix_date,
    COALESCE(journal_entry_last_item_times.last_item_created_at, journal_entries.created_at),
    COALESCE(journal_entry_last_item_times.last_item_created_unix_date, journal_entries.created_unix_date)
FROM journal_entries
LEFT JOIN journal_entry_last_item_times
ON journal_entries.id = journal_entry_last_item_times.journal_entry_id
            """,
            "DROP TABLE journal_entries",
            "ALTER TABLE journal_entries_new RENAME TO journal_entries",
            "CREATE INDEX journal_entries_user_id_canonical_at_index ON journal_entries(user_id, canonical_at)",
            "PRAGMA foreign_keys=on",
        ),
        transaction=False,
    )
