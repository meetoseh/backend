from typing import Optional
from error_middleware import handle_error
from itgs import Itgs
import stripe
import os


async def up(itgs: Itgs):
    """Adds payment_email to course_download_links to avoid having to call stripe everytime
    for this email, since we have to fetch it in the activate flow everytime anyway.
    """
    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    await cursor.executemany2(
        (
            "PRAGMA foreign_keys=OFF",
            "DROP INDEX course_download_links_course_id_idx",
            "DROP INDEX course_download_links_stripe_checkout_session_id_idx",
            "DROP INDEX course_download_links_user_id_idx",
            "DROP INDEX course_download_links_visitor_id_idx",
            """
            CREATE TABLE course_download_links_new (
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
                code TEXT UNIQUE NOT NULL,
                stripe_checkout_session_id TEXT NULL,
                payment_email TEXT NULL,
                user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
                visitor_id INTEGER NULL REFERENCES visitors(id) ON DELETE SET NULL,
                created_at REAL NOT NULL
            )
            """,
            """
            INSERT INTO course_download_links_new (
                id, uid, course_id, code, stripe_checkout_session_id, payment_email, user_id, visitor_id, created_at
            )
            SELECT
                id, uid, course_id, code, stripe_checkout_session_id, NULL, user_id, visitor_id, created_at
            FROM course_download_links
            """,
            "DROP TABLE course_download_links",
            "ALTER TABLE course_download_links_new RENAME TO course_download_links",
            "CREATE INDEX course_download_links_course_id_idx ON course_download_links(course_id)",
            "CREATE INDEX course_download_links_stripe_checkout_session_id_idx ON course_download_links(stripe_checkout_session_id)",
            "CREATE INDEX course_download_links_payment_email_idx ON course_download_links(payment_email)",
            "CREATE INDEX course_download_links_user_id_idx ON course_download_links(user_id)",
            "CREATE INDEX course_download_links_visitor_id_idx ON course_download_links(visitor_id)",
            "PRAGMA foreign_keys=ON",
        ),
        transaction=False,
    )

    last_id: Optional[int] = None
    block_size = 50

    stripe_sk = os.environ["OSEH_STRIPE_SECRET_KEY"]
    while True:
        response = await cursor.execute(
            """
            SELECT
                id, stripe_checkout_session_id
            FROM course_download_links
            WHERE
                (? IS NULL OR id > ?)
            ORDER BY id ASC
            LIMIT ?
            """,
            (last_id, last_id, block_size),
        )

        for row in response.results or []:
            row_id: int = row[0]
            stripe_checkout_session_id: Optional[str] = row[1]
            if stripe_checkout_session_id is None:
                continue

            try:
                checkout_session = stripe.checkout.Session.retrieve(
                    stripe_checkout_session_id, api_key=stripe_sk
                )
                payment_email: str = checkout_session.customer_details.email
                await cursor.execute(
                    """
                    UPDATE course_download_links
                    SET payment_email = ?
                    WHERE id = ?
                    """,
                    (payment_email, row_id),
                )
            except Exception as e:
                await handle_error(
                    e, extra_info=f"{row_id=}, {stripe_checkout_session_id=}"
                )

        if (not response.results) or len(response.results) < block_size:
            break

        last_id = row_id
