import io
import json
import time
from typing import List, Optional, cast
from itgs import Itgs
from migrations.shared.shared_screen_transition_003 import (
    SHARED_SCREEN_TRANSITION_SCHEMA_V003,
)
from lib.client_flows.helper import check_oas_30_schema
from lib.client_flows.screen_cache import purge_client_screen_cache
from temp_files import temp_file


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    files = await itgs.files()

    with temp_file(".bak") as backup_file:
        with open(backup_file, "wb") as f:
            await conn.backup(f)

        with open(backup_file, "rb") as f:
            await files.upload(
                f,
                bucket=files.default_bucket,
                key=f"s3_files/backup/database/timely/0238_speedup_transitions-pre-{int(time.time())}.bak",
                sync=True,
            )

    cursor = conn.cursor("weak")

    batch_size = 10
    last_uid = cast(Optional[str], None)
    while True:
        response = await cursor.execute(
            """
SELECT uid, schema, slug FROM client_screens
WHERE
    (? IS NULL OR uid > ?)
ORDER BY uid ASC
LIMIT ?
            """,
            (last_uid, last_uid, batch_size),
        )

        if not response.results:
            break

        batch_qargs = []
        slugs: List[str] = []
        for row in response.results:
            row_uid = cast(str, row[0])
            row_schema = cast(str, row[1])
            row_slug = cast(str, row[2])

            row_parsed_schema = json.loads(row_schema)
            update_schema(row_parsed_schema)
            check_oas_30_schema(row_parsed_schema, require_example=True)
            batch_qargs.extend((row_uid, json.dumps(row_parsed_schema, sort_keys=True)))
            slugs.append(row_slug)

            last_uid = row_uid

        sql = io.StringIO()
        sql.write("WITH batch(uid, schema) AS (VALUES (?, ?)")
        for _ in range(len(slugs) - 1):
            sql.write(", (?, ?)")
        sql.write(
            ")\nUPDATE client_screens SET schema=b.schema FROM batch b WHERE client_screens.uid=b.uid"
        )
        await cursor.execute(sql.getvalue(), batch_qargs)
        for slug in slugs:
            await purge_client_screen_cache(itgs, slug=slug)

        if len(response.results) < batch_size:
            break

    with temp_file(".bak") as backup_file:
        with open(backup_file, "wb") as f:
            await conn.backup(f)

        with open(backup_file, "rb") as f:
            await files.upload(
                f,
                bucket=files.default_bucket,
                key=f"s3_files/backup/database/timely/0238_speedup_transitions-post-{int(time.time())}.bak",
                sync=True,
            )


def update_schema(schema: dict) -> None:
    if (
        schema["type"] == "object"
        and schema.get("description") == "The animation to use"
    ):
        for k, v in SHARED_SCREEN_TRANSITION_SCHEMA_V003.items():
            schema[k] = v
        return

    for v in cast(dict, schema.get("properties", dict())).values():
        update_schema(v)

    for v in cast(list, schema.get("oneOf", list())):
        update_schema(v)

    if "items" in schema:
        update_schema(cast(dict, schema["items"]))
