try:
    import helper
except:
    import tests.helper

from typing import Optional
import unittest
from itgs import Itgs
import asyncio
from users.me.routes.read_streak import read_streak_from_db
import os
import time
import secrets
from contextlib import asynccontextmanager
from dataclasses import dataclass
import json


@asynccontextmanager
async def temp_user(itgs: Itgs, *, created_at: Optional[float] = None):
    conn = await itgs.conn()
    cursor = conn.cursor("none")

    if created_at is None:
        created_at = time.time()

    new_sub = f"oseh_u_{secrets.token_urlsafe(16)}"
    new_email = f"{secrets.token_urlsafe(8)}@oseh.com"
    new_rc_id = f"oseh_u_rc_{secrets.token_urlsafe(16)}"
    await cursor.execute(
        """
        INSERT INTO users (
            sub, email, email_verified, given_name, family_name, admin, revenue_cat_id, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            new_sub,
            new_email,
            1,
            "Test",
            "User",
            0,
            new_rc_id,
            created_at,
        ),
    )

    try:
        yield new_sub
    finally:
        await cursor.execute("DELETE FROM users WHERE sub=?", (new_sub,))


@asynccontextmanager
async def temp_prompt(itgs: Itgs, *, created_at: Optional[float] = None):
    conn = await itgs.conn()
    cursor = conn.cursor("none")

    if created_at is None:
        created_at = time.time()

    prompt_uid = f"oseh_ip_{secrets.token_urlsafe(16)}"
    await cursor.execute(
        """
        INSERT INTO interactive_prompts (
            uid, prompt, duration_seconds, created_at
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            prompt_uid,
            json.dumps({"style": "press", "text": "Press and hold"}),
            20,
            created_at,
        ),
    )

    try:
        yield prompt_uid
    finally:
        await cursor.execute(
            "DELETE FROM interactive_prompts WHERE uid=?", (prompt_uid,)
        )


@dataclass
class TempDailyEvent:
    daily_event_uid: str
    journey_uid: str
    prompt_uid: str
    created_at: float
    available_at: Optional[float]


_sent = object()


@asynccontextmanager
async def temp_daily_event(
    itgs: Itgs,
    *,
    prompt_uid: str,
    created_at: Optional[float] = None,
    available_at: Optional[float] = _sent,
):
    if created_at is None:
        created_at = time.time()

    if available_at is _sent:
        available_at = created_at

    conn = await itgs.conn()
    cursor = conn.cursor("none")

    j_uid = f"oseh_j_{secrets.token_urlsafe(16)}"
    de_uid = f"oseh_de_{secrets.token_urlsafe(16)}"
    dej_uid = f"oseh_dej_{secrets.token_urlsafe(16)}"

    await cursor.executemany3(
        (
            (
                """
                INSERT INTO journeys (
                    uid, audio_content_file_id, background_image_file_id, blurred_background_image_file_id,
                    darkened_background_image_file_id, instructor_id, title, description,
                    journey_subcategory_id, interactive_prompt_id, created_at
                )
                SELECT
                    ?, journey_audio_contents.content_file_id, bknds.image_file_id, bknds.blurred_image_file_id,
                    bknds.darkened_image_file_id, instructors.id, ?, ?, journey_subcategories.id,
                    interactive_prompts.id, ?
                FROM journey_audio_contents, journey_background_images AS bknds, instructors, journey_subcategories, interactive_prompts
                WHERE
                    NOT EXISTS (
                        SELECT 1 FROM journey_audio_contents AS jac2 WHERE jac2.id > journey_audio_contents.id
                    )
                    AND NOT EXISTS (
                        SELECT 1 FROM journey_background_images AS jbi2 WHERE jbi2.id > bknds.id
                    )
                    AND NOT EXISTS (
                        SELECT 1 FROM instructors AS i2 WHERE i2.id > instructors.id
                    )
                    AND NOT EXISTS (
                        SELECT 1 FROM journey_subcategories AS jsc2 WHERE jsc2.id > journey_subcategories.id
                    )
                    AND interactive_prompts.uid = ?
                """,
                (
                    j_uid,
                    "Test Journey",
                    "Test Journey Description",
                    created_at,
                    prompt_uid,
                ),
            ),
            (
                """
                INSERT INTO daily_events (
                    uid, available_at, created_at
                )
                VALUES (?, ?, ?)
                """,
                (de_uid, available_at, created_at),
            ),
            (
                """
                INSERT INTO daily_event_journeys (
                    uid, daily_event_id, journey_id, created_at
                )
                SELECT ?, daily_events.id, journeys.id, ?
                FROM daily_events, journeys
                WHERE daily_events.uid = ? AND journeys.uid = ?
                """,
                (dej_uid, created_at, de_uid, j_uid),
            ),
        )
    )

    try:
        yield TempDailyEvent(
            daily_event_uid=de_uid,
            journey_uid=j_uid,
            prompt_uid=prompt_uid,
            created_at=created_at,
            available_at=available_at,
        )
    finally:
        await cursor.executemany3(
            (
                (
                    "DELETE FROM journeys WHERE uid=?",
                    (j_uid,),
                ),
                (
                    "DELETE FROM daily_events WHERE uid=?",
                    (de_uid,),
                ),
            )
        )


async def create_session(itgs: Itgs, *, user_sub: str, prompt_uid: str):
    session_uid: str = f"oseh_ips_{secrets.token_urlsafe(16)}"

    conn = await itgs.conn()
    cursor = conn.cursor("none")

    await cursor.execute(
        """
        INSERT INTO interactive_prompt_sessions (
            interactive_prompt_id, user_id, uid
        )
        SELECT
            interactive_prompts.id, users.id, ?
        FROM interactive_prompts, users
        WHERE
            interactive_prompts.uid = ?
            AND users.sub = ?
        """,
        (session_uid, prompt_uid, user_sub),
    )


if os.environ["ENVIRONMENT"] != "test":

    class Test(unittest.TestCase):
        def test_new_user_streak(self):
            async def _inner():
                async with Itgs() as itgs, temp_user(itgs) as user_sub:
                    streak = await read_streak_from_db(
                        itgs, user_sub=user_sub, now=time.time()
                    )
                    self.assertEqual(streak, 0)

            asyncio.run(_inner())

        def test_user_with_unrelated_prompt_streak(self):
            async def _inner():
                async with Itgs() as itgs, temp_user(itgs) as user_sub, temp_prompt(
                    itgs
                ) as prompt:
                    streak = await read_streak_from_db(
                        itgs, user_sub=user_sub, now=time.time()
                    )
                    self.assertEqual(streak, 0)

                    await create_session(itgs, user_sub=user_sub, prompt_uid=prompt)
                    streak = await read_streak_from_db(
                        itgs, user_sub=user_sub, now=time.time()
                    )
                    self.assertEqual(streak, 0)

            asyncio.run(_inner())

        def test_user_with_one_day_streak(self):
            async def _inner():
                async with Itgs() as itgs, temp_user(itgs) as user_sub, temp_prompt(
                    itgs
                ) as prompt, temp_daily_event(itgs, prompt_uid=prompt):
                    streak = await read_streak_from_db(
                        itgs, user_sub=user_sub, now=time.time()
                    )
                    self.assertEqual(streak, 0)

                    await create_session(itgs, user_sub=user_sub, prompt_uid=prompt)
                    streak = await read_streak_from_db(
                        itgs, user_sub=user_sub, now=time.time()
                    )
                    self.assertEqual(streak, 1)

            asyncio.run(_inner())

        def test_user_with_two_day_streak(self):
            async def _inner():
                now = time.time()
                yesterday = now - 86400

                async with Itgs() as itgs, temp_user(itgs) as user_sub, temp_prompt(
                    itgs, created_at=yesterday
                ) as prompt1, temp_daily_event(
                    itgs, prompt_uid=prompt1, created_at=yesterday
                ), temp_prompt(
                    itgs, created_at=now
                ) as prompt2, temp_daily_event(
                    itgs, prompt_uid=prompt2, created_at=now
                ):
                    streak = await read_streak_from_db(
                        itgs, user_sub=user_sub, now=now + 1
                    )
                    self.assertEqual(streak, 0)

                    await create_session(itgs, user_sub=user_sub, prompt_uid=prompt1)
                    streak = await read_streak_from_db(
                        itgs, user_sub=user_sub, now=now + 1
                    )
                    self.assertEqual(streak, 0)

                    await create_session(itgs, user_sub=user_sub, prompt_uid=prompt2)
                    streak = await read_streak_from_db(
                        itgs, user_sub=user_sub, now=now + 1
                    )
                    self.assertEqual(streak, 2)

            asyncio.run(_inner())

        def test_user_with_gap_streak(self):
            async def _inner():
                now = time.time()
                two_days_ago = now - 86400 * 2
                yesterday = now - 86400

                async with Itgs() as itgs, temp_user(itgs) as user_sub, temp_prompt(
                    itgs, created_at=two_days_ago
                ) as prompt1, temp_daily_event(
                    itgs, prompt_uid=prompt1, created_at=two_days_ago
                ), temp_prompt(
                    itgs, created_at=yesterday
                ) as prompt2, temp_daily_event(
                    itgs, prompt_uid=prompt2, created_at=yesterday
                ), temp_prompt(
                    itgs, created_at=now
                ) as prompt3, temp_daily_event(
                    itgs, prompt_uid=prompt3, created_at=now
                ):
                    streak = await read_streak_from_db(
                        itgs, user_sub=user_sub, now=now + 1
                    )
                    self.assertEqual(streak, 0)

                    await create_session(itgs, user_sub=user_sub, prompt_uid=prompt1)
                    streak = await read_streak_from_db(
                        itgs, user_sub=user_sub, now=now + 1
                    )
                    self.assertEqual(streak, 0)

                    await create_session(itgs, user_sub=user_sub, prompt_uid=prompt3)
                    streak = await read_streak_from_db(
                        itgs, user_sub=user_sub, now=now + 1
                    )
                    self.assertEqual(streak, 1)

                    await create_session(itgs, user_sub=user_sub, prompt_uid=prompt2)
                    streak = await read_streak_from_db(
                        itgs, user_sub=user_sub, now=now + 1
                    )
                    self.assertEqual(streak, 3)

            asyncio.run(_inner())

    if __name__ == "__main__":
        unittest.main()
