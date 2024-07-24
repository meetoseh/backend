import io
import time
from typing import List, Optional, Tuple, cast
from client_flows.lib.parse_flow_screens import decode_flow_screens, encode_flow_screens
from itgs import Itgs
from temp_files import temp_file


async def up(itgs: Itgs):
    """migration 0213 led to a change in the default value for a client flow screen; this
    doesn't cause an issue in using the flow screens in e.g., triggers, but it leads to
    a precondition failure if you try to edit a flow without editing the screens, which is
    inconvenient

    This goes through every flow and patches the flow screens to the current
    canonical representation, which will have rules set to {"trigger": null,
    "peek": null} if they are not present
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
                key=f"s3_files/backup/database/timely/0214_round_trip_flow_screens-pre-{int(time.time())}.bak",
                sync=True,
            )

    cursor = conn.cursor("weak")

    last_uid: Optional[str] = None
    while True:
        response = await cursor.execute(
            "SELECT uid, screens FROM client_flows WHERE (? IS NULL OR uid > ?) ORDER BY uid ASC LIMIT 20",
            (last_uid, last_uid),
        )

        if not response.results:
            break

        batch: List[Tuple[str, str]] = []
        for row in response.results:
            row_uid = cast(str, row[0])
            row_raw_screens = cast(str, row[1])

            last_uid = row_uid

            round_tripped_screens = encode_flow_screens(
                decode_flow_screens(row_raw_screens)
            )
            if round_tripped_screens == row_raw_screens:
                continue

            batch.append((row_uid, round_tripped_screens))

        if batch:
            query = io.StringIO()
            query.write("WITH batch (uid, screens) AS (VALUES (?, ?)")
            qargs = []
            for idx, (uid, screens) in enumerate(batch):
                if idx != 0:
                    query.write(", (?, ?)")
                qargs.append(uid)
                qargs.append(screens)

            query.write(
                ") UPDATE client_flows SET screens = batch.screens FROM batch WHERE client_flows.uid = batch.uid"
            )
            await cursor.execute(query.getvalue(), qargs)

    files = await itgs.files()

    with temp_file(".bak") as backup_file:
        with open(backup_file, "wb") as f:
            await conn.backup(f)

        with open(backup_file, "rb") as f:
            await files.upload(
                f,
                bucket=files.default_bucket,
                key=f"s3_files/backup/database/timely/0214_round_trip_flow_screens-post-{int(time.time())}.bak",
                sync=True,
            )
