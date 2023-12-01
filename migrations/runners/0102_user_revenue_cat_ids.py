"""Adds support for multiple revenue cat ids associated with a single user
to facilitate merge account flows. This migration does not delete the old
revenue cat id column; that's done in the next migration
"""
import json
import secrets
from typing import Optional, cast
from itgs import Itgs
from temp_files import temp_file
import time
from dataclasses import dataclass
import io
import asyncio
import socket


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor("weak")
    files = await itgs.files()
    rc = await itgs.revenue_cat()

    with temp_file(".bak") as backup_file:
        with open(backup_file, "wb") as f:
            await conn.backup(f)

        with open(backup_file, "rb") as f:
            await files.upload(
                f,
                bucket=files.default_bucket,
                key=f"s3_files/backup/database/timely/0102_user_revenue_cat_ids-{int(time.time())}.bak",
                sync=True,
            )

    await cursor.executemany2(
        (
            """
            CREATE TABLE user_revenue_cat_ids (
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                revenue_cat_id TEXT UNIQUE NOT NULL,
                revenue_cat_attributes TEXT NOT NULL,
                created_at REAL NOT NULL,
                checked_at REAL NOT NULL
            )
            """,
            "CREATE INDEX user_revenue_cat_ids_user_created_at_idx ON user_revenue_cat_ids(user_id, created_at)",
        ),
        transaction=False,
    )

    slack = await itgs.slack()

    last_user_sub: Optional[str] = None
    while True:
        response = await cursor.execute(
            """
            SELECT
                users.sub,
                users.revenue_cat_id
            FROM users
            WHERE
                NOT EXISTS (SELECT 1 FROM user_revenue_cat_ids AS urc WHERE urc.user_id = users.id)
                AND (? IS NULL OR users.sub > ?)
            ORDER BY users.sub ASC
            LIMIT 100
            """,
            (last_user_sub, last_user_sub),
        )
        if not response.results:
            break
        batch_at = time.time()
        to_migrate: list[_UserToMigrate] = []
        for row in response.results:
            row_user_sub = cast(str, row[0])
            row_revenue_cat_id = cast(str, row[1])

            customer_info = await rc.get_customer_info(
                revenue_cat_id=row_revenue_cat_id, handle_ratelimits=True
            )
            row_attributes = customer_info.subscriber.subscriber_attributes
            to_migrate.append(
                _UserToMigrate(
                    sub=row_user_sub,
                    revenue_cat_id=row_revenue_cat_id,
                    revenue_cat_attributes=json.dumps(
                        dict((k, v.model_dump()) for k, v in row_attributes.items())
                    ),
                )
            )

        query = io.StringIO()
        query.write("WITH batch(uid, sub, rcid, rcattrs) AS (VALUES (?, ?, ?, ?)")
        for _ in range(1, len(to_migrate)):
            query.write(", (?, ?, ?, ?)")
        query.write(
            ") INSERT INTO user_revenue_cat_ids ("
            " uid, user_id, revenue_cat_id, revenue_cat_attributes, created_at, checked_at"
            ") SELECT"
            " batch.uid, users.id, batch.rcid, batch.rcattrs, ?, ? "
            "FROM batch "
            "JOIN users ON users.sub = batch.sub"
        )

        qargs = []
        for user in to_migrate:
            qargs.extend(
                (
                    f"oseh_iurc_{secrets.token_urlsafe(16)}",
                    user.sub,
                    user.revenue_cat_id,
                    user.revenue_cat_attributes,
                )
            )

        qargs.extend((batch_at, batch_at))
        response = await cursor.execute(query.getvalue(), qargs)
        await slack.send_ops_message(
            f"{socket.gethostname()}: 0102_user_revenue_cat_ids.py: {response.rows_affected}/{len(to_migrate)} rows migrated in batch"
        )
        last_user_sub = to_migrate[-1].sub
        await asyncio.sleep(60)


@dataclass
class _UserToMigrate:
    sub: str
    revenue_cat_id: str
    revenue_cat_attributes: str
