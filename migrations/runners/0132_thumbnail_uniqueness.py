from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()
    await cursor.executemany2(
        (
            "CREATE UNIQUE INDEX course_video_thumbnail_images_image_id_for_user_source_idx"
            " ON course_video_thumbnail_images(image_file_id)"
            " WHERE json_extract(source, '$.type') = 'user'",
            "CREATE UNIQUE INDEX course_video_thumbnail_images_image_id_for_frame_source_idx"
            " ON course_video_thumbnail_images(image_file_id, json_extract(source, '$.video_sha512', '$.via_sha512', '$.frame_number'))"
            " WHERE json_extract(source, '$.type') = 'frame'",
        ),
        transaction=False,
    )
