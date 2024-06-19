import time
from itgs import Itgs
from typing import List, Optional, Tuple, cast
import base64
import gzip
import json
import io

from lib.client_flows.flow_cache import purge_client_flow_cache
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
                key=f"s3_files/backup/database/timely/0191_add_client_flow_screen_flags-{int(time.time())}.bak",
                sync=True,
            )

    cursor = conn.cursor("weak")

    initial_flags = 1 | 2 | 4
    # iOS, Android, Web, but avoiding importing from main code within migration

    print("Updating client flows...")
    last_slug: Optional[str] = None
    while True:
        response = await cursor.execute(
            "SELECT slug, screens FROM client_flows WHERE (? IS NULL OR slug > ?) ORDER BY slug ASC LIMIT 5",
            (last_slug, last_slug),
        )

        if not response.results:
            break

        new_rows: List[Tuple[str, str]] = []
        for row in response.results:
            row_slug = cast(str, row[0])
            row_screens_b85 = cast(str, row[1])

            row_screens_gz = base64.b85decode(row_screens_b85)
            row_screens_json = gzip.decompress(row_screens_gz)
            row_screens = json.loads(row_screens_json)

            assert isinstance(
                row_screens, list
            ), f"{row_slug=} has {type(row_screens)=}"

            new_row_screens = [
                {**screen, "flags": initial_flags} for screen in row_screens
            ]
            new_row_screens_json = json.dumps(new_row_screens, sort_keys=True).encode(
                "utf-8"
            )
            new_row_screens_gz = gzip.compress(
                new_row_screens_json, compresslevel=9, mtime=0
            )
            new_row_screens_b85 = base64.b85encode(new_row_screens_gz).decode("ascii")
            new_rows.append((row_slug, new_row_screens_b85))

            last_slug = row_slug

        query = io.StringIO()
        query.write("WITH batch(slug, screens) AS (VALUES (?, ?)")
        for _ in range(len(new_rows) - 1):
            query.write(", (?, ?)")

        qargs = []
        for new_slug, new_screens_b85 in new_rows:
            qargs.extend([new_slug, new_screens_b85])

        query.write(
            ") UPDATE client_flows SET screens = batch.screens FROM batch WHERE client_flows.slug = batch.slug"
        )

        response = await cursor.execute(query.getvalue(), qargs)
        assert response.rows_affected == len(new_rows)
        print(f"Updated the following flows: {[row[0] for row in new_rows]}")

        for changed_slug, _screens in new_rows:
            await purge_client_flow_cache(itgs, slug=changed_slug)
    print("All done updating client flows")

    print("Updating user client screens...")
    last_uid: Optional[str] = None
    while True:
        response = await cursor.execute(
            "SELECT uid, screen FROM user_client_screens WHERE (? IS NULL OR uid > ?) ORDER BY uid ASC LIMIT 25",
            (last_uid, last_uid),
        )
        if not response.results:
            break

        new_rows: List[Tuple[str, str]] = []
        for row in response.results:
            row_uid = cast(str, row[0])
            row_screen_json = cast(str, row[1])
            row_screen = json.loads(row_screen_json)

            assert isinstance(row_screen, dict), f"{row_uid=} has {type(row_screen)=}"

            new_row_screen = {**row_screen, "flags": initial_flags}
            new_row_screen_json = json.dumps(new_row_screen, sort_keys=True)
            new_rows.append((row_uid, new_row_screen_json))

            last_uid = row_uid

        query = io.StringIO()
        query.write("WITH batch(uid, screen) AS (VALUES (?, ?)")
        for _ in range(len(new_rows) - 1):
            query.write(", (?, ?)")

        qargs = []
        for new_uid, new_screen_json in new_rows:
            qargs.extend([new_uid, new_screen_json])

        query.write(
            ") UPDATE user_client_screens SET screen = batch.screen FROM batch WHERE user_client_screens.uid = batch.uid"
        )

        response = await cursor.execute(query.getvalue(), qargs)
        assert response.rows_affected == len(new_rows)
    print("All done updating user client screens")
