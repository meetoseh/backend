from itgs import Itgs


async def up(itgs: Itgs):
    conn = await itgs.conn()
    cursor = conn.cursor("strong")

    await cursor.executemany2(
        (
            """
CREATE TABLE onboarding_videos (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    purpose TEXT NOT NULL,
    video_content_file_id INTEGER NOT NULL REFERENCES content_files(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    thumbnail_image_file_id INTEGER NOT NULL REFERENCES image_files(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    active_at REAL,
    visible_in_admin BOOLEAN NOT NULL,
    created_at REAL NOT NULL
)
            """,
            "CREATE UNIQUE INDEX onboarding_videos_content_file_id_purpose_idx ON onboarding_videos(video_content_file_id, purpose)",
            "CREATE UNIQUE INDEX onboarding_videos_purpose_active_idx ON onboarding_videos(purpose) WHERE active_at IS NOT NULL",
            "CREATE INDEX onboarding_videos_thumbnail_image_file_id_idx ON onboarding_videos(thumbnail_image_file_id)",
            "CREATE INDEX onboarding_videos_purpose_type_active_idx ON onboarding_videos(json_extract(purpose, '$.type')) WHERE active_at IS NOT NULL",
            "CREATE INDEX onboarding_videos_purpose_type_created_at_uid_idx ON onboarding_videos(json_extract(purpose, '$.type'), created_at, uid) WHERE visible_in_admin",
            """
CREATE TABLE onboarding_video_uploads (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    content_file_id INTEGER UNIQUE NOT NULL REFERENCES content_files(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    uploaded_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL ON UPDATE RESTRICT,
    last_uploaded_at REAL NOT NULL
)
            """,
            "CREATE INDEX onboarding_video_uploads_uploaded_by_user_id_idx ON onboarding_video_uploads(uploaded_by_user_id)",
            "CREATE INDEX onboarding_video_uploads_last_uploaded_at_idx ON onboarding_video_uploads(last_uploaded_at)",
            """
CREATE TABLE onboarding_video_thumbnails (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    image_file_id INTEGER NOT NULL REFERENCES image_files(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    source TEXT NOT NULL,
    last_uploaded_at REAL NOT NULL
)
            """,
            "CREATE INDEX onboarding_video_thumbnails_user_sub_idx ON onboarding_video_thumbnails(json_extract(source, '$.sub')) WHERE json_extract(source, '$.type') = 'user'",
            "CREATE INDEX onboarding_video_thumbnails_video_sha512_idx ON onboarding_video_thumbnails(json_extract(source, '$.video_sha512')) WHERE json_extract(source, '$.type') = 'frame'",
            "CREATE INDEX onboarding_video_thumbnails_last_uploaded_at_idx ON onboarding_video_thumbnails(last_uploaded_at)",
            """
CREATE UNIQUE INDEX onboarding_video_thumbnails_image_id_for_user_source_idx
  ON onboarding_video_thumbnails(image_file_id)
  WHERE json_extract(source, '$.type') = 'user'
            """,
            """
CREATE UNIQUE INDEX onboarding_video_thumbnails_image_id_for_frame_source_idx
  ON onboarding_video_thumbnails(image_file_id, json_extract(source, '$.video_sha512', '$.via_sha512', '$.frame_number'))
  WHERE json_extract(source, '$.type') = 'frame'
            """,
        ),
        transaction=False,
    )
