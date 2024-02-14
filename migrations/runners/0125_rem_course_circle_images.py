from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor("strong")

    response = await cursor.executeunified2(
        (
            """
            SELECT
                image_files.uid
            FROM courses, image_files
            WHERE
                image_files.id = courses.circle_image_file_id
            """,
            "UPDATE courses SET circle_image_file_id = NULL",
        )
    )

    if response[0].results:
        jobs = await itgs.jobs()

        for (uid,) in response[0].results:
            await jobs.enqueue("runners.delete_image_file", uid=uid)

    await cursor.executemany2(
        (
            "PRAGMA foreign_keys=OFF",
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
                created_at REAL NOT NULL
            )
            """,
            """
            INSERT INTO courses_new(
                id, uid, slug, flags, revenue_cat_entitlement, title, title_short, description, background_image_file_id, created_at
            )
            SELECT
                id, uid, slug, flags, revenue_cat_entitlement, title, title_short, description, background_image_file_id, created_at
            FROM courses
            """,
            "DROP TABLE courses",
            "ALTER TABLE courses_new RENAME TO courses",
            "CREATE INDEX courses_background_image_file_id_idx ON courses(background_image_file_id)",
            "PRAGMA foreign_keys=ON",
        ),
        transaction=False,
    )
