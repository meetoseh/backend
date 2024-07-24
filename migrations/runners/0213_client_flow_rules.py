from itgs import Itgs


async def up(itgs: Itgs) -> None:
    """Adds rules column to client_flows, initialized as an empty array for each flow"""

    conn = await itgs.conn()
    cursor = conn.cursor()
    await cursor.executeunified2(
        (
            "PRAGMA foreign_keys = OFF",
            "DROP INDEX client_flows_created_at_idx",
            """
CREATE TABLE client_flows_new (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    name TEXT NULL,
    description TEXT NULL,
    client_schema TEXT NOT NULL,
    server_schema TEXT NOT NULL,
    replaces BOOLEAN NOT NULL,
    screens TEXT NOT NULL,
    rules TEXT NOT NULL,
    flags INTEGER NOT NULL,
    created_at REAL NOT NULL
)
            """,
            """
INSERT INTO client_flows_new (
    id, uid, slug, name, description, client_schema, server_schema, replaces, screens, rules, flags, created_at
)
SELECT
    id, uid, slug, name, description, client_schema, server_schema, replaces, screens, '[]', flags, created_at
FROM client_flows
            """,
            "DROP TABLE client_flows",
            "ALTER TABLE client_flows_new RENAME TO client_flows",
            "CREATE INDEX client_flows_created_at_idx ON client_flows (created_at)",
            "PRAGMA foreign_keys = ON",
        ),
        transaction=False,
        read_consistency="strong",
    )
