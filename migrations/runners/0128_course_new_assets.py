from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.executemany2(
        (
            """
            CREATE TABLE course_videos (
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                content_file_id INTEGER UNIQUE NOT NULL REFERENCES content_files(id) ON DELETE CASCADE ON UPDATE RESTRICT,
                uploaded_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL ON UPDATE RESTRICT,
                last_uploaded_at REAL NOT NULL
            )
            """,
            "CREATE INDEX course_videos_uploaded_by_user_id_idx ON course_videos(uploaded_by_user_id)",
            "CREATE INDEX course_videos_last_uploaded_at_idx ON course_videos(last_uploaded_at)",
            """
            CREATE TABLE course_video_thumbnail_images (
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                image_file_id INTEGER UNIQUE NOT NULL REFERENCES image_files(id) ON DELETE CASCADE ON UPDATE RESTRICT,
                source TEXT NOT NULL,
                last_uploaded_at REAL NOT NULL
            )
            """,
            "CREATE INDEX course_video_thumbnail_iamges_user_sub_idx ON course_video_thumbnail_images(json_extract(source, '$.sub')) WHERE json_extract(source, '$.type') = 'user'",
            "CREATE INDEX course_video_thumbnail_iamges_video_sha512_idx ON course_video_thumbnail_images(json_extract(source, '$.video_sha512')) WHERE json_extract(source, '$.type') = 'frame'",
            "CREATE INDEX course_video_thumbnail_images_last_uploaded_at_idx ON course_video_thumbnail_images(last_uploaded_at)",
            """
            CREATE TABLE course_background_images(
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                original_image_file_id INTEGER UNIQUE NOT NULL REFERENCES image_files(id) ON DELETE CASCADE ON UPDATE RESTRICT,
                darkened_image_file_id INTEGER UNIQUE NOT NULL REFERENCES image_files(id) ON DELETE CASCADE ON UPDATE RESTRICT,
                uploaded_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL ON UPDATE RESTRICT,
                last_uploaded_at REAL NOT NULL
            )
            """,
            "CREATE INDEX course_background_images_uploaded_by_user_id_idx ON course_background_images(uploaded_by_user_id)",
            """
            CREATE TABLE course_logo_images (
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                image_file_id INTEGER UNIQUE NOT NULL REFERENCES image_files(id) ON DELETE CASCADE ON UPDATE RESTRICT,
                uploaded_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL ON UPDATE RESTRICT,
                last_uploaded_at REAL NOT NULL
            )
            """,
            "CREATE INDEX course_logo_images_uploaded_by_user_id_idx ON course_logo_images(uploaded_by_user_id)",
            "CREATE INDEX course_logo_images_last_uploaded_at_idx ON course_logo_images(last_uploaded_at)",
            """
            CREATE TABLE course_hero_images(
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                image_file_id INTEGER UNIQUE NOT NULL REFERENCES image_files(id) ON DELETE CASCADE ON UPDATE RESTRICT,
                uploaded_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL ON UPDATE RESTRICT,
                last_uploaded_at REAL NOT NULL
            )
            """,
            "CREATE INDEX course_hero_images_uploaded_by_user_id_idx ON course_hero_images(uploaded_by_user_id)",
            "CREATE INDEX course_hero_images_last_uploaded_at_idx ON course_hero_images(last_uploaded_at)",
            "PRAGMA foreign_keys=OFF",
            "DROP INDEX courses_instructor_id_idx",
            "DROP INDEX courses_background_image_file_id_idx",
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
                created_at REAL NOT NULL
            )
            """,
            """
            INSERT INTO courses_new(
                id, uid, slug, flags, revenue_cat_entitlement, title, description, instructor_id, background_original_image_file_id, background_darkened_image_file_id, video_content_file_id, video_thumbnail_image_file_id, logo_image_file_id, hero_image_file_id, created_at
            )
            SELECT
                id, uid, slug, flags, revenue_cat_entitlement, title, description, instructor_id, background_image_file_id, NULL, NULL, NULL, NULL, NULL, created_at
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
            "CREATE INDEX courses_created_at_series_listing_idx ON courses(created_at) WHERE (flags & 64) != 0",
            "PRAGMA foreign_keys=ON",
        ),
        transaction=False,
    )
