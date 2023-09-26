import time
from itgs import Itgs
from temp_files import temp_file


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    files = await itgs.files()
    with temp_file(".bak") as backup_file:
        with open(backup_file, "wb") as f:
            await conn.backup(f)

        with open(backup_file, "rb") as f:
            await files.upload(
                f,
                bucket=files.default_bucket,
                key=f"s3_files/backup/database/timely/0083_del_old_notifications_table-{int(time.time())}.bak",
                sync=True,
            )

    await cursor.executemany2(
        ("DROP TABLE user_notification_clicks", "DROP TABLE user_notifications"),
        transaction=False,
    )
