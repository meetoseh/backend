from itgs import Itgs


async def up(itgs: Itgs):
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.executemany2(
        (
            "PRAGMA foreign_keys=off",
            "DROP INDEX courses_instructor_id_idx",
            "DROP INDEX courses_background_original_image_file_id_idx",
            "DROP INDEX courses_background_darkened_image_file_id_idx",
            "DROP INDEX courses_video_content_file_id_idx",
            "DROP INDEX courses_video_thumbnail_image_file_id_idx",
            "DROP INDEX courses_logo_image_file_id_idx",
            "DROP INDEX courses_hero_image_file_id_idx",
            "DROP INDEX courses_created_at_series_listing_idx",
            """
CREATE TABLE courses_new(
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    flags INTEGER NOT NULL,
    revenue_cat_entitlement TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    instructor_id INTEGER NOT NULL REFERENCES instructors(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    background_original_image_file_id INTEGER NULL REFERENCES image_files(id) ON DELETE SET NULL ON UPDATE RESTRICT,
    background_darkened_image_file_id INTEGER NULL REFERENCES image_files(id) ON DELETE SET NULL ON UPDATE RESTRICT,
    video_content_file_id INTEGER NULL REFERENCES content_files(id) ON DELETE SET NULL ON UPDATE RESTRICT,
    video_thumbnail_image_file_id INTEGER NULL REFERENCES image_files(id) ON DELETE SET NULL ON UPDATE RESTRICT,
    logo_image_file_id INTEGER NULL REFERENCES image_files(id) ON DELETE SET NULL ON UPDATE RESTRICT,
    hero_image_file_id INTEGER NULL REFERENCES image_files(id) ON DELETE SET NULL ON UPDATE RESTRICT,
    share_image_file_id INTEGER NULL REFERENCES image_files(id) ON DELETE SET NULL ON UPDATE RESTRICT,
    created_at REAL NOT NULL
)
            """,
            """
INSERT INTO courses_new(
    id, uid, slug, flags, revenue_cat_entitlement, title, description, instructor_id,
    background_original_image_file_id, background_darkened_image_file_id, video_content_file_id,
    video_thumbnail_image_file_id, logo_image_file_id, hero_image_file_id, 
    share_image_file_id, created_at
)
SELECT
    id, uid, slug, flags, revenue_cat_entitlement, title, description, instructor_id,
    background_original_image_file_id, background_darkened_image_file_id, video_content_file_id,
    video_thumbnail_image_file_id, logo_image_file_id, hero_image_file_id, 
    NULL, created_at
FROM courses
            """,
            "DROP TABLE courses",
            "ALTER TABLE courses_new RENAME TO courses",
            "CREATE INDEX courses_instructor_id_idx ON courses(instructor_id)",
            "CREATE INDEX courses_background_original_image_file_id_idx ON courses(background_original_image_file_id)",
            "CREATE INDEX courses_background_darkened_image_file_id_idx ON courses(background_darkened_image_file_id)",
            "CREATE INDEX courses_video_content_file_id_idx ON courses(video_content_file_id)",
            "CREATE INDEX courses_video_thumbnail_image_file_id_idx ON courses(video_thumbnail_image_file_id)",
            "CREATE INDEX courses_logo_image_file_id_idx ON courses(logo_image_file_id)",
            "CREATE INDEX courses_hero_image_file_id_idx ON courses(hero_image_file_id)",
            "CREATE INDEX courses_share_image_file_id_idx ON courses(share_image_file_id)",
            "CREATE INDEX courses_created_at_series_listing_idx ON courses(created_at) WHERE (flags & 64) != 0",
            "PRAGMA foreign_keys=on",
        ),
        transaction=False,
    )
