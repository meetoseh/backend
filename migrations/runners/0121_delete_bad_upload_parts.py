from itgs import Itgs


async def up(itgs: Itgs):
    conn = await itgs.conn()
    cursor = conn.cursor()
    await cursor.execute(
        "DELETE FROM s3_file_upload_parts "
        "WHERE"
        " NOT EXISTS ("
        "  SELECT 1 FROM s3_file_uploads"
        "  WHERE"
        "   s3_file_upload_parts.s3_file_upload_id = s3_file_uploads.id"
        " )"
    )
