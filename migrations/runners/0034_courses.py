"""Adds course-related tables, where a course is a programmed set of lessons."""

from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    await cursor.execute(
        """
        CREATE TABLE courses(
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            slug TEXT UNIQUE NOT NULL,
            revenue_cat_entitlement TEXT NOT NULL,
            title TEXT NOT NULL,
            title_short TEXT NOT NULL,
            description TEXT NOT NULL,
            background_image_file_id INTEGER NULL REFERENCES image_files(id) ON DELETE SET NULL,
            circle_image_file_id INTEGER NULL REFERENCES image_files(id) ON DELETE SET NULL,
            created_at REAL NOT NULL
        )
        """
    )
    await cursor.execute(
        "CREATE INDEX courses_background_image_file_id_idx ON courses(background_image_file_id)"
    )
    await cursor.execute(
        "CREATE INDEX courses_circle_image_file_id_idx ON courses(circle_image_file_id)"
    )

    await cursor.execute(
        """
        CREATE TABLE course_exports (
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            inputs_hash TEXT NOT NULL,
            s3_file_id INTEGER NOT NULL REFERENCES s3_files(id) ON DELETE CASCADE,
            output_sha512 TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    await cursor.execute(
        "CREATE INDEX course_exports_course_id_cat_idx ON course_exports(course_id, created_at)"
    )
    await cursor.execute(
        "CREATE INDEX course_exports_s3_file_id_idx ON course_exports(s3_file_id)"
    )

    await cursor.execute(
        """
        CREATE TABLE course_journeys (
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            journey_id INTEGER NOT NULL REFERENCES journeys(id) ON DELETE CASCADE,
            priority INTEGER NOT NULL
        )
        """
    )
    await cursor.execute(
        "CREATE UNIQUE INDEX course_journeys_course_priority_idx ON course_journeys(course_id, priority)"
    )
    await cursor.execute(
        "CREATE INDEX course_journeys_journey_idx ON course_journeys(journey_id)"
    )

    await cursor.execute(
        """
        CREATE TABLE course_users (
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            last_priority INTEGER NULL,
            last_journey_at REAL NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )
    await cursor.execute(
        "CREATE UNIQUE INDEX course_users_course_user_idx ON course_users(course_id, user_id)"
    )
    await cursor.execute(
        "CREATE INDEX course_users_user_created_at_idx ON course_users(user_id, created_at)"
    )

    await cursor.execute(
        """
        CREATE TABLE course_user_classes (
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            course_user_id INTEGER NOT NULL REFERENCES course_users(id) ON DELETE CASCADE,
            journey_id INTEGER NOT NULL REFERENCES journeys(id) ON DELETE CASCADE,
            created_at REAL NOT NULL
        )
        """
    )
    await cursor.execute(
        "CREATE INDEX course_user_classes_course_user_id_idx ON course_user_classes(course_user_id)"
    )
    await cursor.execute(
        "CREATE INDEX course_user_classes_journey_id_idx ON course_user_classes(journey_id)"
    )

    await cursor.execute(
        """
        CREATE TABLE course_download_links (
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            code TEXT UNIQUE NOT NULL,
            stripe_checkout_session_id TEXT NULL,
            user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
            visitor_id INTEGER NULL REFERENCES visitors(id) ON DELETE SET NULL,
            created_at REAL NOT NULL
        )
        """
    )
    await cursor.execute(
        "CREATE INDEX course_download_links_course_id_idx ON course_download_links(course_id)"
    )
    await cursor.execute(
        "CREATE INDEX course_download_links_stripe_checkout_session_id_idx ON course_download_links(stripe_checkout_session_id)"
    )
    await cursor.execute(
        "CREATE INDEX course_download_links_user_id_idx ON course_download_links(user_id)"
    )
    await cursor.execute(
        "CREATE INDEX course_download_links_visitor_id_idx ON course_download_links(visitor_id)"
    )

    await cursor.execute(
        """
        CREATE TABLE course_download_link_clicks (
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            course_download_link_id INTEGER NOT NULL REFERENCES course_download_links(id) ON DELETE CASCADE,
            course_export_id INTEGER NULL REFERENCES course_exports(id) ON DELETE SET NULL,
            visitor_id INTEGER NULL REFERENCES visitors(id) ON DELETE SET NULL,
            created_at REAL NOT NULL
        )
        """
    )
    await cursor.execute(
        "CREATE INDEX course_download_link_clicks_cdl_id_idx ON course_download_link_clicks(course_download_link_id, created_at)"
    )
    await cursor.execute(
        "CREATE INDEX course_download_link_clicks_export_id_idx ON course_download_link_clicks(course_export_id)"
    )
    await cursor.execute(
        "CREATE INDEX course_download_link_clicks_visitor_id_idx ON course_download_link_clicks(visitor_id)"
    )
