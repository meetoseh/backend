from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.executemany2(
        (
            "PRAGMA foreign_keys=off",
            "DROP INDEX courses_background_image_file_id_idx",
            "DROP INDEX courses_circle_image_file_id_idx",
            """
            CREATE TABLE courses_new(
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                slug TEXT UNIQUE NOT NULL,
                flags INTEGER NOT NULL,
                revenue_cat_entitlement TEXT NOT NULL,
                title TEXT NOT NULL,
                title_short TEXT NOT NULL,
                description TEXT NOT NULL,
                background_image_file_id INTEGER NULL REFERENCES image_files(id) ON DELETE SET NULL,
                circle_image_file_id INTEGER NULL REFERENCES image_files(id) ON DELETE SET NULL,
                created_at REAL NOT NULL
            )
            """,
            """
            INSERT INTO courses_new(
                id, uid, slug, flags, revenue_cat_entitlement, title, title_short, description, background_image_file_id, circle_image_file_id, created_at
            )
            SELECT
                courses.id,
                courses.uid,
                courses.slug,
                CASE WHEN courses.slug IN ('resilient-spirit-07202023', 'elevate-within-080882023') THEN 1598 ELSE 1406 END,
                courses.revenue_cat_entitlement,
                courses.title,
                courses.title_short,
                courses.description,
                courses.background_image_file_id,
                courses.circle_image_file_id,
                courses.created_at
            FROM courses
            """,
            "DROP TABLE courses",
            "ALTER TABLE courses_new RENAME TO courses",
            "CREATE INDEX courses_background_image_file_id_idx ON courses(background_image_file_id)",
            "CREATE INDEX courses_circle_image_file_id_idx ON courses(circle_image_file_id)",
            "PRAGMA foreign_keys=on",
        ),
        transaction=False,
    )
