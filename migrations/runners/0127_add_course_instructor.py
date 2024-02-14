from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.executemany2(
        (
            "PRAGMA foreign_keys=OFF",
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
                background_image_file_id INTEGER NULL REFERENCES image_files(id) ON DELETE SET NULL,
                created_at REAL NOT NULL
            )
            """,
            """
            INSERT INTO courses_new(
                id, uid, slug, flags, revenue_cat_entitlement, title, description, instructor_id, background_image_file_id, created_at
            )
            SELECT
                courses.id, 
                courses.uid, 
                courses.slug, 
                courses.flags, 
                courses.revenue_cat_entitlement, 
                courses.title, 
                courses.description, 
                instructors.id, 
                courses.background_image_file_id, 
                courses.created_at
            FROM courses, instructors
            WHERE
                EXISTS (
                    SELECT 1 FROM course_journeys, journeys
                    WHERE
                        course_journeys.course_id = courses.id
                        AND course_journeys.journey_id = journeys.id
                        AND journeys.instructor_id = instructors.id
                        AND NOT EXISTS (
                            SELECT 1 FROM course_journeys AS cj
                            WHERE
                                cj.course_id = courses.id
                                AND (
                                    cj.priority < course_journeys.priority
                                    OR (
                                        cj.priority = course_journeys.priority
                                        AND cj.uid < course_journeys.uid
                                    )
                                )
                        )
                )
            """,
            "DROP TABLE courses",
            "ALTER TABLE courses_new RENAME TO courses",
            "CREATE INDEX courses_instructor_id_idx ON courses(instructor_id)",
            "CREATE INDEX courses_background_image_file_id_idx ON courses(background_image_file_id)",
            "PRAGMA foreign_keys=ON",
        ),
        transaction=False,
    )
