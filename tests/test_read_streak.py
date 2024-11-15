# type: ignore

try:
    import helper  # type: ignore
except:
    import tests.helper  # type: ignore

from typing import Literal, Optional, Union, cast
import unittest
from itgs import Itgs
import asyncio
from users.lib.streak import (
    read_prev_best_streak_from_db,
    read_streak_from_db,
    read_days_of_week_from_db,
    read_total_journeys_from_db,
)
import os
import time
import secrets
from contextlib import asynccontextmanager
from dataclasses import dataclass
import json
from enum import Enum
import pytz
import unix_dates


tz = cast(pytz.BaseTzInfo, pytz.FixedOffset(-480))


@asynccontextmanager
async def temp_user(itgs: Itgs, *, created_at: Optional[float] = None):
    conn = await itgs.conn()
    cursor = conn.cursor("none")

    if created_at is None:
        created_at = time.time()

    new_sub = f"oseh_u_{secrets.token_urlsafe(16)}"
    await cursor.execute(
        """
        INSERT INTO users (
            sub, given_name, family_name, admin, timezone, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            new_sub,
            "Test",
            "User",
            0,
            "America/Los_Angeles",
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
class TempJourney:
    journey_uid: str
    prompt_uid: str
    created_at: float
    available_at: Optional[float]


class _NotSetEnum(Enum):
    NotSet = 0


_sent = _NotSetEnum.NotSet


@asynccontextmanager
async def temp_journey(
    itgs: Itgs,
    *,
    prompt_uid: str,
    created_at: Optional[float] = None,
    available_at: Union[float, Literal[_NotSetEnum.NotSet], None] = _sent,
):
    if created_at is None:
        created_at = time.time()

    if available_at is _sent:
        available_at = created_at

    conn = await itgs.conn()
    cursor = conn.cursor("none")

    j_uid = f"oseh_j_{secrets.token_urlsafe(16)}"
    de_uid = f"oseh_de_{secrets.token_urlsafe(16)}"

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
        )
    )

    try:
        yield TempJourney(
            journey_uid=j_uid,
            prompt_uid=prompt_uid,
            created_at=created_at,
            available_at=available_at,
        )
    finally:
        await cursor.execute(
            "DELETE FROM journeys WHERE uid=?",
            (j_uid,),
        )


@asynccontextmanager
async def temp_journey2(
    itgs: Itgs,
    *,
    created_at: Optional[float] = None,
    available_at: Union[float, Literal[_NotSetEnum.NotSet], None] = _sent,
):
    """Convenience function which combines temp_prompt and temp_journey"""
    async with temp_prompt(itgs, created_at=created_at) as prompt, temp_journey(
        itgs, prompt_uid=prompt, created_at=created_at, available_at=available_at
    ) as journey:
        yield journey


async def create_prompt_event(
    itgs: Itgs, *, user_sub: str, prompt_uid: str, join_at: float, leave_at: float
):
    session_uid: str = f"oseh_ips_{secrets.token_urlsafe(16)}"
    join_uid: str = f"oseh_ipe_{secrets.token_urlsafe(16)}"
    leave_uid: str = f"oseh_ipe_{secrets.token_urlsafe(16)}"

    conn = await itgs.conn()
    cursor = conn.cursor("none")

    await cursor.executemany3(
        (
            (
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
            ),
            (
                """
                INSERT INTO interactive_prompt_events (
                    uid, interactive_prompt_session_id, evtype, data, prompt_time, created_at
                )
                SELECT
                    ?, interactive_prompt_sessions.id, 'join', '{}', ?, ?
                FROM interactive_prompt_sessions
                WHERE
                    interactive_prompt_sessions.uid = ?
                """,
                (join_uid, 0, join_at, session_uid),
            ),
            (
                """
                INSERT INTO interactive_prompt_events (
                    uid, interactive_prompt_session_id, evtype, data, prompt_time, created_at
                )
                SELECT
                    ?, interactive_prompt_sessions.id, 'leave', '{}', ?, ?
                FROM interactive_prompt_sessions
                WHERE
                    interactive_prompt_sessions.uid = ?
                """,
                (leave_uid, max(0, leave_at - join_at), leave_at, session_uid),
            ),
        )
    )


async def create_user_journey(
    itgs: Itgs, *, user_sub: str, journey_uid: str, created_at: float
) -> str:
    """Stores in the simple fashion that the user with the given sub took the
    journey with the given uid.

    Returns the journey_user_uid created
    """
    journey_user_uid = f"oseh_uj_{secrets.token_urlsafe(16)}"
    conn = await itgs.conn()
    cursor = conn.cursor("none")

    response = await cursor.execute(
        """
        INSERT INTO user_journeys (
            uid, user_id, journey_id, created_at, created_at_unix_date
        )
        SELECT
            ?, users.id, journeys.id, ?, ?
        FROM users, journeys
        WHERE
            users.sub = ?
            AND journeys.uid = ?
        """,
        (
            journey_user_uid,
            created_at,
            unix_dates.unix_timestamp_to_unix_date(created_at, tz=tz),
            user_sub,
            journey_uid,
        ),
    )
    assert response.rows_affected == 1
    return journey_user_uid


async def simulate_user_in_journey(
    itgs: Itgs,
    *,
    user_sub: str,
    journey_uid: str,
    prompt_uid: str,
    join_at: float,
    leave_at: float,
):
    """Combines create_prompt_event and create_user_journey as they normally would
    be called together. Prior to user_journeys being created, queries would go through
    interactive_prompts in a rather complicated fashion, but now the user_journeys
    table is sufficient to determine user streaks. Furthermore, streaks should not
    rely on prompt events anymore as they are less reliable for future potential flows,
    like users opting out of prompts altogether.
    """
    await create_prompt_event(
        itgs,
        user_sub=user_sub,
        prompt_uid=prompt_uid,
        join_at=join_at,
        leave_at=leave_at,
    )
    await create_user_journey(
        itgs,
        user_sub=user_sub,
        journey_uid=journey_uid,
        created_at=join_at,
    )


if os.environ["ENVIRONMENT"] != "test":

    def _today(now: Optional[float] = None):
        if now is None:
            now = time.time()
        return unix_dates.unix_timestamp_to_unix_date(now, tz=tz)

    class Test(unittest.TestCase):
        def test_new_user_streak(self):
            async def _inner():
                async with Itgs() as itgs, temp_user(itgs) as user_sub:
                    streak = await read_streak_from_db(
                        itgs, user_sub=user_sub, unix_date_today=_today()
                    )
                    self.assertEqual(streak, 0)

            asyncio.run(_inner())

        def test_user_with_old_prompt_streak(self):
            async def _inner():
                now = time.time()
                one_week_ago = now - 60 * 60 * 24 * 7
                async with Itgs() as itgs, temp_user(
                    itgs, created_at=one_week_ago
                ) as user_sub, temp_prompt(itgs, created_at=one_week_ago) as prompt:
                    streak = await read_streak_from_db(
                        itgs, user_sub=user_sub, unix_date_today=_today(now)
                    )
                    self.assertEqual(streak, 0)

                    await create_prompt_event(
                        itgs,
                        user_sub=user_sub,
                        prompt_uid=prompt,
                        join_at=one_week_ago,
                        leave_at=one_week_ago + 1,
                    )
                    streak = await read_streak_from_db(
                        itgs, user_sub=user_sub, unix_date_today=_today(now)
                    )
                    self.assertEqual(streak, 0)

            asyncio.run(_inner())

        def test_user_with_one_day_streak(self):
            async def _inner():
                async with Itgs() as itgs, temp_user(itgs) as user_sub, temp_prompt(
                    itgs
                ) as prompt, temp_journey(itgs, prompt_uid=prompt) as journey:
                    now = time.time()
                    streak = await read_streak_from_db(
                        itgs, user_sub=user_sub, unix_date_today=_today(now)
                    )
                    self.assertEqual(streak, 0)

                    await simulate_user_in_journey(
                        itgs,
                        user_sub=user_sub,
                        prompt_uid=prompt,
                        journey_uid=journey.journey_uid,
                        join_at=now,
                        leave_at=now + 1,
                    )
                    streak = await read_streak_from_db(
                        itgs, user_sub=user_sub, unix_date_today=_today(now)
                    )
                    self.assertEqual(streak, 1)

            asyncio.run(_inner())

        def test_user_with_old_one_day_streak(self):
            async def _inner():
                async with Itgs() as itgs, temp_user(itgs) as user_sub, temp_prompt(
                    itgs
                ) as prompt, temp_journey(itgs, prompt_uid=prompt) as journey:
                    now = time.time()
                    streak = await read_streak_from_db(
                        itgs, user_sub=user_sub, unix_date_today=_today(now)
                    )
                    self.assertEqual(streak, 0)

                    await simulate_user_in_journey(
                        itgs,
                        user_sub=user_sub,
                        prompt_uid=prompt,
                        journey_uid=journey.journey_uid,
                        join_at=now - 86402,
                        leave_at=now - 86401,
                    )
                    streak = await read_streak_from_db(
                        itgs, user_sub=user_sub, unix_date_today=_today(now)
                    )
                    self.assertEqual(streak, 1)

            asyncio.run(_inner())

        def test_user_with_two_day_old_streak(self):
            async def _inner():
                now = time.time()
                two_days_ago = now - 86400 * 2
                async with Itgs() as itgs, temp_user(itgs) as user_sub, temp_prompt(
                    itgs
                ) as prompt, temp_journey(itgs, prompt_uid=prompt) as journey:
                    now = time.time()
                    streak = await read_streak_from_db(
                        itgs, user_sub=user_sub, unix_date_today=_today(now)
                    )
                    self.assertEqual(streak, 0)

                    await simulate_user_in_journey(
                        itgs,
                        user_sub=user_sub,
                        prompt_uid=prompt,
                        journey_uid=journey.journey_uid,
                        join_at=two_days_ago - 1,
                        leave_at=two_days_ago,
                    )
                    streak = await read_streak_from_db(
                        itgs, user_sub=user_sub, unix_date_today=_today(now)
                    )
                    self.assertEqual(streak, 0)

            asyncio.run(_inner())

        def test_user_with_prompt_events_without_user_journey(self):
            async def _inner():
                async with Itgs() as itgs, temp_user(itgs) as user_sub, temp_prompt(
                    itgs
                ) as prompt, temp_journey(itgs, prompt_uid=prompt) as journey:
                    now = time.time()
                    streak = await read_streak_from_db(
                        itgs, user_sub=user_sub, unix_date_today=_today(now)
                    )
                    self.assertEqual(streak, 0)

                    await create_prompt_event(
                        itgs,
                        user_sub=user_sub,
                        prompt_uid=prompt,
                        join_at=now,
                        leave_at=now + 1,
                    )
                    streak = await read_streak_from_db(
                        itgs, user_sub=user_sub, unix_date_today=_today(now)
                    )
                    self.assertEqual(streak, 0)

            asyncio.run(_inner())

        def test_user_with_user_journey_no_prompt(self):
            async def _inner():
                async with Itgs() as itgs, temp_user(itgs) as user_sub, temp_prompt(
                    itgs
                ) as prompt, temp_journey(itgs, prompt_uid=prompt) as journey:
                    now = time.time()
                    streak = await read_streak_from_db(
                        itgs, user_sub=user_sub, unix_date_today=_today(now)
                    )
                    self.assertEqual(streak, 0)

                    await create_user_journey(
                        itgs,
                        user_sub=user_sub,
                        journey_uid=journey.journey_uid,
                        created_at=now,
                    )
                    streak = await read_streak_from_db(
                        itgs, user_sub=user_sub, unix_date_today=_today(now)
                    )
                    self.assertEqual(streak, 1)

            asyncio.run(_inner())

        def test_user_with_two_day_streak(self):
            async def _inner():
                now = time.time()
                yesterday = now - 86400

                async with Itgs() as itgs, temp_user(itgs) as user_sub, temp_prompt(
                    itgs, created_at=yesterday
                ) as prompt1, temp_journey(
                    itgs, prompt_uid=prompt1, created_at=yesterday
                ) as journey1, temp_prompt(
                    itgs, created_at=now
                ) as prompt2, temp_journey(
                    itgs, prompt_uid=prompt2, created_at=now
                ) as journey2:
                    streak = await read_streak_from_db(
                        itgs, user_sub=user_sub, unix_date_today=_today(now)
                    )
                    self.assertEqual(streak, 0)

                    await simulate_user_in_journey(
                        itgs,
                        user_sub=user_sub,
                        prompt_uid=prompt1,
                        journey_uid=journey1.journey_uid,
                        join_at=yesterday,
                        leave_at=yesterday + 1,
                    )
                    streak = await read_streak_from_db(
                        itgs, user_sub=user_sub, unix_date_today=_today(now)
                    )
                    self.assertEqual(streak, 1)

                    await simulate_user_in_journey(
                        itgs,
                        user_sub=user_sub,
                        prompt_uid=prompt2,
                        journey_uid=journey2.journey_uid,
                        join_at=now,
                        leave_at=now + 1,
                    )
                    streak = await read_streak_from_db(
                        itgs, user_sub=user_sub, unix_date_today=_today(now)
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
                ) as prompt1, temp_journey(
                    itgs, prompt_uid=prompt1, created_at=two_days_ago
                ) as journey1, temp_prompt(
                    itgs, created_at=yesterday
                ) as prompt2, temp_journey(
                    itgs, prompt_uid=prompt2, created_at=yesterday
                ) as journey2, temp_prompt(
                    itgs, created_at=now
                ) as prompt3, temp_journey(
                    itgs, prompt_uid=prompt3, created_at=now
                ) as journey3:
                    streak = await read_streak_from_db(
                        itgs, user_sub=user_sub, unix_date_today=_today(now)
                    )
                    self.assertEqual(streak, 0)

                    await simulate_user_in_journey(
                        itgs,
                        user_sub=user_sub,
                        prompt_uid=prompt1,
                        journey_uid=journey1.journey_uid,
                        join_at=two_days_ago,
                        leave_at=two_days_ago + 1,
                    )
                    streak = await read_streak_from_db(
                        itgs, user_sub=user_sub, unix_date_today=_today(now)
                    )
                    self.assertEqual(streak, 0)

                    await simulate_user_in_journey(
                        itgs,
                        user_sub=user_sub,
                        prompt_uid=prompt3,
                        journey_uid=journey3.journey_uid,
                        join_at=now,
                        leave_at=now + 1,
                    )
                    streak = await read_streak_from_db(
                        itgs, user_sub=user_sub, unix_date_today=_today(now)
                    )
                    self.assertEqual(streak, 1)

                    await simulate_user_in_journey(
                        itgs,
                        user_sub=user_sub,
                        prompt_uid=prompt2,
                        journey_uid=journey2.journey_uid,
                        join_at=yesterday,
                        leave_at=yesterday + 1,
                    )
                    streak = await read_streak_from_db(
                        itgs, user_sub=user_sub, unix_date_today=_today(now)
                    )
                    self.assertEqual(streak, 3)

            asyncio.run(_inner())

    class TestDaysOfWeekPracticed(unittest.TestCase):
        def test_new_user(self):
            async def _inner():
                async with Itgs() as itgs, temp_user(itgs) as user_sub:
                    streak = await read_days_of_week_from_db(
                        itgs, user_sub=user_sub, unix_date_today=_today()
                    )
                    self.assertEqual(streak, [])

            asyncio.run(_inner())

        def test_with_monday(self):
            async def _inner():
                now = 1682953200  # 2023-05-01 8am pst
                async with Itgs() as itgs, temp_user(itgs) as user_sub, temp_prompt(
                    itgs
                ) as prompt, temp_journey(itgs, prompt_uid=prompt) as journey:
                    streak = await read_days_of_week_from_db(
                        itgs, user_sub=user_sub, unix_date_today=_today(now)
                    )
                    self.assertEqual(streak, [])

                    await simulate_user_in_journey(
                        itgs,
                        user_sub=user_sub,
                        prompt_uid=prompt,
                        journey_uid=journey.journey_uid,
                        join_at=now,
                        leave_at=now + 1,
                    )

                    for i in range(7):
                        streak = await read_days_of_week_from_db(
                            itgs, user_sub=user_sub, unix_date_today=_today(now) + i
                        )
                        self.assertEqual(streak, ["Monday"])

                    streak = await read_days_of_week_from_db(
                        itgs, user_sub=user_sub, unix_date_today=_today(now) + 7
                    )
                    self.assertEqual(streak, [])

            asyncio.run(_inner())

        def test_with_tuesday(self):
            async def _inner():
                now = 1683039600  # 2023-05-02 8am pst
                async with Itgs() as itgs, temp_user(itgs) as user_sub, temp_prompt(
                    itgs
                ) as prompt, temp_journey(itgs, prompt_uid=prompt) as journey:
                    streak = await read_days_of_week_from_db(
                        itgs, user_sub=user_sub, unix_date_today=_today(now)
                    )
                    self.assertEqual(streak, [])

                    await simulate_user_in_journey(
                        itgs,
                        user_sub=user_sub,
                        prompt_uid=prompt,
                        journey_uid=journey.journey_uid,
                        join_at=now,
                        leave_at=now + 1,
                    )
                    for i in range(6):
                        streak = await read_days_of_week_from_db(
                            itgs, user_sub=user_sub, unix_date_today=_today(now) + i
                        )
                        self.assertEqual(streak, ["Tuesday"])

                    streak = await read_days_of_week_from_db(
                        itgs, user_sub=user_sub, unix_date_today=_today(now) + 6
                    )
                    self.assertEqual(streak, [])

            asyncio.run(_inner())

        def test_with_wednesday_sunday(self):
            async def _inner():
                wed = 1683126000  # 2023-05-03 8am pst
                sun = wed + 86400 * 4
                async with Itgs() as itgs, temp_user(itgs) as user_sub, temp_prompt(
                    itgs
                ) as prompt, temp_journey(itgs, prompt_uid=prompt) as journey:
                    streak = await read_days_of_week_from_db(
                        itgs, user_sub=user_sub, unix_date_today=_today(wed)
                    )
                    self.assertEqual(streak, [])

                    await simulate_user_in_journey(
                        itgs,
                        user_sub=user_sub,
                        prompt_uid=prompt,
                        journey_uid=journey.journey_uid,
                        join_at=wed,
                        leave_at=wed + 1,
                    )
                    streak = await read_days_of_week_from_db(
                        itgs, user_sub=user_sub, unix_date_today=_today(wed)
                    )
                    self.assertEqual(streak, ["Wednesday"])

                    await simulate_user_in_journey(
                        itgs,
                        user_sub=user_sub,
                        prompt_uid=prompt,
                        journey_uid=journey.journey_uid,
                        join_at=sun,
                        leave_at=sun + 1,
                    )
                    streak = await read_days_of_week_from_db(
                        itgs, user_sub=user_sub, unix_date_today=_today(wed)
                    )
                    self.assertEqual(streak, ["Wednesday"])
                    streak = await read_days_of_week_from_db(
                        itgs, user_sub=user_sub, unix_date_today=_today(sun)
                    )
                    self.assertEqual(streak, ["Wednesday", "Sunday"])

                    streak = await read_days_of_week_from_db(
                        itgs, user_sub=user_sub, unix_date_today=_today(sun) + 1
                    )
                    self.assertEqual(streak, [])

            asyncio.run(_inner())

    class TestTotalJourneys(unittest.TestCase):
        def test_new_user(self):
            async def _inner():
                async with Itgs() as itgs, temp_user(itgs) as user_sub:
                    cnt = await read_total_journeys_from_db(itgs, user_sub=user_sub)
                    self.assertEqual(cnt, 0)

            asyncio.run(_inner())

        def test_one_journey(self):
            async def _inner():
                async with Itgs() as itgs, temp_user(itgs) as user_sub, temp_journey2(
                    itgs
                ) as journey:
                    cnt = await read_total_journeys_from_db(itgs, user_sub=user_sub)
                    self.assertEqual(cnt, 0)

                    await create_user_journey(
                        itgs,
                        user_sub=user_sub,
                        journey_uid=journey.journey_uid,
                        created_at=time.time(),
                    )
                    cnt = await read_total_journeys_from_db(itgs, user_sub=user_sub)
                    self.assertEqual(cnt, 1)

        def test_many_journeys(self):
            async def _inner():
                async with Itgs() as itgs, temp_user(itgs) as user_sub, temp_journey2(
                    itgs
                ) as journey:
                    cnt = await read_total_journeys_from_db(itgs, user_sub=user_sub)
                    self.assertEqual(cnt, 0)

                    for _ in range(10):
                        await create_user_journey(
                            itgs,
                            user_sub=user_sub,
                            journey_uid=journey.journey_uid,
                            created_at=time.time(),
                        )
                    cnt = await read_total_journeys_from_db(itgs, user_sub=user_sub)
                    self.assertEqual(cnt, 10)

            asyncio.run(_inner())

    class TestPrevBestStreak(unittest.TestCase):
        def test_new_user_streak(self):
            async def _inner():
                async with Itgs() as itgs, temp_user(itgs) as user_sub:
                    streak = await read_prev_best_streak_from_db(
                        itgs, user_sub=user_sub, unix_date_today=_today()
                    )
                    self.assertEqual(streak, 0)

            asyncio.run(_inner())

        def test_current_one_day_streak(self):
            async def _inner():
                now = time.time()
                async with Itgs() as itgs, temp_user(itgs) as user_sub, temp_journey2(
                    itgs,
                ) as journey:
                    streak = await read_prev_best_streak_from_db(
                        itgs, user_sub=user_sub, unix_date_today=_today(now)
                    )
                    self.assertEqual(streak, 0)

                    await simulate_user_in_journey(
                        itgs,
                        user_sub=user_sub,
                        journey_uid=journey.journey_uid,
                        prompt_uid=journey.prompt_uid,
                        join_at=now,
                        leave_at=now + 1,
                    )
                    streak = await read_prev_best_streak_from_db(
                        itgs, user_sub=user_sub, unix_date_today=_today(now)
                    )
                    self.assertEqual(streak, 0)

            asyncio.run(_inner())

        def test_old_one_day_streak(self):
            async def _inner():
                now = time.time()
                yesterday = now - 86400
                async with Itgs() as itgs, temp_user(itgs) as user_sub, temp_journey2(
                    itgs,
                ) as journey:
                    streak = await read_prev_best_streak_from_db(
                        itgs, user_sub=user_sub, unix_date_today=_today(now)
                    )
                    self.assertEqual(streak, 0)

                    await simulate_user_in_journey(
                        itgs,
                        user_sub=user_sub,
                        journey_uid=journey.journey_uid,
                        prompt_uid=journey.prompt_uid,
                        join_at=yesterday,
                        leave_at=yesterday + 1,
                    )
                    streak = await read_prev_best_streak_from_db(
                        itgs, user_sub=user_sub, unix_date_today=_today(now)
                    )
                    self.assertEqual(streak, 1)

            asyncio.run(_inner())

        def test_older_one_day_streak(self):
            async def _inner():
                now = time.time()
                two_days_ago = now - 86400 * 2
                async with Itgs() as itgs, temp_user(itgs) as user_sub, temp_journey2(
                    itgs,
                ) as journey:
                    streak = await read_prev_best_streak_from_db(
                        itgs, user_sub=user_sub, unix_date_today=_today(now)
                    )
                    self.assertEqual(streak, 0)

                    await simulate_user_in_journey(
                        itgs,
                        user_sub=user_sub,
                        journey_uid=journey.journey_uid,
                        prompt_uid=journey.prompt_uid,
                        join_at=two_days_ago,
                        leave_at=two_days_ago + 1,
                    )
                    streak = await read_prev_best_streak_from_db(
                        itgs, user_sub=user_sub, unix_date_today=_today(now)
                    )
                    self.assertEqual(streak, 1)

            asyncio.run(_inner())

        def test_current_two_day_streak(self):
            async def _inner():
                now = time.time()
                yesterday = now - 86400
                async with Itgs() as itgs, temp_user(itgs) as user_sub, temp_journey2(
                    itgs,
                ) as journey:
                    streak = await read_prev_best_streak_from_db(
                        itgs, user_sub=user_sub, unix_date_today=_today(now)
                    )
                    self.assertEqual(streak, 0)

                    await simulate_user_in_journey(
                        itgs,
                        user_sub=user_sub,
                        journey_uid=journey.journey_uid,
                        prompt_uid=journey.prompt_uid,
                        join_at=yesterday,
                        leave_at=yesterday + 1,
                    )
                    streak = await read_prev_best_streak_from_db(
                        itgs, user_sub=user_sub, unix_date_today=_today(now)
                    )
                    self.assertEqual(streak, 1)

                    await simulate_user_in_journey(
                        itgs,
                        user_sub=user_sub,
                        journey_uid=journey.journey_uid,
                        prompt_uid=journey.prompt_uid,
                        join_at=now,
                        leave_at=now + 1,
                    )
                    streak = await read_prev_best_streak_from_db(
                        itgs, user_sub=user_sub, unix_date_today=_today(now)
                    )
                    self.assertEqual(streak, 0)

            asyncio.run(_inner())

        def test_old_and_current_one_day_streak(self):
            async def _inner():
                now = time.time()
                two_days_ago = now - 86400 * 2
                async with Itgs() as itgs, temp_user(itgs) as user_sub, temp_journey2(
                    itgs,
                ) as journey:
                    streak = await read_prev_best_streak_from_db(
                        itgs, user_sub=user_sub, unix_date_today=_today(now)
                    )
                    self.assertEqual(streak, 0)

                    await simulate_user_in_journey(
                        itgs,
                        user_sub=user_sub,
                        journey_uid=journey.journey_uid,
                        prompt_uid=journey.prompt_uid,
                        join_at=two_days_ago,
                        leave_at=two_days_ago + 1,
                    )
                    streak = await read_prev_best_streak_from_db(
                        itgs, user_sub=user_sub, unix_date_today=_today(now)
                    )
                    self.assertEqual(streak, 1)

                    await simulate_user_in_journey(
                        itgs,
                        user_sub=user_sub,
                        journey_uid=journey.journey_uid,
                        prompt_uid=journey.prompt_uid,
                        join_at=now,
                        leave_at=now + 1,
                    )
                    streak = await read_prev_best_streak_from_db(
                        itgs, user_sub=user_sub, unix_date_today=_today(now)
                    )
                    self.assertEqual(streak, 1)

            asyncio.run(_inner())

        def test_two_day_then_one_day_then_current_one_day_streak(self):
            async def _inner():
                now = time.time()
                async with Itgs() as itgs, temp_user(itgs) as user_sub, temp_journey2(
                    itgs,
                ) as journey:
                    streak = await read_prev_best_streak_from_db(
                        itgs, user_sub=user_sub, unix_date_today=_today(now)
                    )
                    self.assertEqual(streak, 0)

                    for days_ago in [4, 3, 1, 0]:
                        await simulate_user_in_journey(
                            itgs,
                            user_sub=user_sub,
                            journey_uid=journey.journey_uid,
                            prompt_uid=journey.prompt_uid,
                            join_at=now - 86400 * days_ago,
                            leave_at=now - 86400 * days_ago + 1,
                        )
                    streak = await read_prev_best_streak_from_db(
                        itgs, user_sub=user_sub, unix_date_today=_today(now)
                    )
                    self.assertEqual(streak, 2)

            asyncio.run(_inner())

        def test_long_gaps(self):
            async def _inner():
                now = time.time()
                async with Itgs() as itgs, temp_user(itgs) as user_sub, temp_journey2(
                    itgs,
                ) as journey:
                    streak = await read_prev_best_streak_from_db(
                        itgs, user_sub=user_sub, unix_date_today=_today(now)
                    )
                    self.assertEqual(streak, 0)

                    for days_ago in [
                        210,
                        190,
                        185,
                        184,
                        183,
                        182,
                        140,
                        139,
                        50,
                        40,
                        30,
                        1,
                        0,
                    ]:
                        await simulate_user_in_journey(
                            itgs,
                            user_sub=user_sub,
                            journey_uid=journey.journey_uid,
                            prompt_uid=journey.prompt_uid,
                            join_at=now - 86400 * days_ago,
                            leave_at=now - 86400 * days_ago + 1,
                        )
                    streak = await read_prev_best_streak_from_db(
                        itgs, user_sub=user_sub, unix_date_today=_today(now)
                    )
                    self.assertEqual(streak, 4)

            asyncio.run(_inner())

    if __name__ == "__main__":
        unittest.main()
