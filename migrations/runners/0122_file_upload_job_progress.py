from itgs import Itgs


async def up(itgs: Itgs) -> None:
    """Adds `job_progress_uid` to `s3_file_uploads`"""

    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.execute(
        "ALTER TABLE s3_file_uploads ADD COLUMN job_progress_uid TEXT NULL"
    )
