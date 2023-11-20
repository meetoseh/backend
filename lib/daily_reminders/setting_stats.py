import json
from typing import Optional, Literal
from lib.redis_stats_preparer import RedisStatsPreparer
from pydantic import BaseModel, Field, validator
from itgs import Itgs


PRESETS = {
    "email": {
        "morning": (21600, 39600),
        "afternoon": (46800, 57600),
        "evening": (61200, 68400),
    },
    "sms": {
        "morning": (28800, 39600),
        "afternoon": (46800, 57600),
        "evening": (57600, 61200),
    },
    "push": {
        "morning": (21600, 39600),
        "afternoon": (46800, 57600),
        "evening": (61200, 68400),
    },
}
# Mutating this is not sufficient to update everything as some values
# are embedded in sql queries or other repos


class DailyReminderTimeRange(BaseModel):
    start: Optional[int] = Field(
        None,
        ge=0,
        lt=60 * 60 * 24,
        description="The minimum number of seconds after midnight before a notification should be sent",
    )
    end: Optional[int] = Field(
        None,
        ge=0,
        lt=60 * 60 * 24 * 2,
        description="The maximum number of seconds after midnight a notification should be sent",
    )
    preset: Optional[Literal["unspecified", "morning", "afternoon", "evening"]] = Field(
        None, description="A preset, which cannot be used with start or end"
    )

    @validator("preset")
    def preset_xor_start_end(cls, v, values):
        if v is not None and (
            values.get("start") is not None or values.get("end") is not None
        ):
            raise ValueError("preset cannot be used with start or end")
        if v is None and (values.get("start") is None or values.get("end") is None):
            raise ValueError(
                "start and end must be used together if preset is not used"
            )
        return v

    @validator("end")
    def end_ge_start(cls, v, values):
        if v is not None and values.get("start") is not None and v < values["start"]:
            raise ValueError("end must be greater than or equal to start")
        return v

    @property
    def for_extra(self) -> str:
        """Formats this time range for use in an event extra"""
        if self.preset is not None:
            return self.preset
        return f"{self.start}-{self.end}"

    def effective_start(self, channel: Literal["email", "sms", "push"]) -> int:
        """Applies the preset (if applicable) to the given channel to get the start time"""
        if self.preset is None:
            assert self.start is not None, self
            return self.start
        preset = PRESETS.get(channel, PRESETS["sms"])
        return preset.get(self.preset, preset["morning"])[0]

    def effective_end(self, channel: Literal["email", "sms", "push"]) -> int:
        """Applies the preset (if applicable) to the given channel to get the end time"""
        if self.preset is None:
            assert self.end is not None, self
            return self.end
        preset = PRESETS.get(channel, PRESETS["sms"])
        return preset.get(self.preset, preset["morning"])[1]

    @classmethod
    def parse_db_obj(cls, db: dict) -> "DailyReminderTimeRange":
        if db["type"] == "preset":
            return DailyReminderTimeRange(preset=db["preset"], start=None, end=None)
        else:
            return DailyReminderTimeRange(start=db["start"], end=db["end"], preset=None)

    @classmethod
    def parse_db(cls, db: str) -> "DailyReminderTimeRange":
        parsed = json.loads(db)
        return cls.parse_db_obj(parsed)

    def db_representation(self) -> str:
        return json.dumps(
            {"type": "preset", "preset": self.preset}
            if self.preset is not None
            else {"type": "explicit", "start": self.start, "end": self.end}
        )


class DailyReminderSettingStatsPreparer:
    """A basic helper class for updating daily reminder setting stats"""

    def __init__(self, stats: RedisStatsPreparer):
        self.stats = stats

    def incr_daily_reminder_settings(
        self,
        unix_date: int,
        event: str,
        *,
        event_extra: Optional[bytes] = None,
        amt: int = 1,
    ) -> None:
        """Updates the given event in stats:daily_reminder_settings:daily:{unix_date}"""
        self.stats.incrby(
            unix_date=unix_date,
            basic_key_format="stats:daily_reminder_settings:daily:{unix_date}",
            earliest_key=b"stats:daily_reminder_settings:daily:earliest",
            event=event,
            event_extra_format="stats:daily_reminder_settings:daily:{unix_date}:extra:{event}",
            event_extra=event_extra,
            amt=amt,
        )

    def _make_extra(
        self,
        old_day_of_week_mask: int,
        old_time_range: DailyReminderTimeRange,
        new_day_of_week_mask: int,
        new_time_range: DailyReminderTimeRange,
    ) -> bytes:
        if (
            old_day_of_week_mask == new_day_of_week_mask
            and old_time_range == new_time_range
        ):
            return b":|:"

        if old_day_of_week_mask == new_day_of_week_mask:
            return f":{old_time_range.for_extra}|:{new_time_range.for_extra}".encode(
                "utf-8"
            )

        if old_time_range == new_time_range:
            return f"{old_day_of_week_mask:>07b}:|{new_day_of_week_mask:>07b}:".encode(
                "utf-8"
            )

        return f"{old_day_of_week_mask:>07b}:{old_time_range.for_extra}|{new_day_of_week_mask:>07b}:{new_time_range.for_extra}".encode(
            "utf-8"
        )

    def incr_sms(
        self,
        unix_date: int,
        *,
        old_day_of_week_mask: int,
        old_time_range: DailyReminderTimeRange,
        new_day_of_week_mask: int,
        new_time_range: DailyReminderTimeRange,
        amt: int = 1,
    ) -> None:
        """Increments the number of users which changed their daily reminder sms settings"""
        self.incr_daily_reminder_settings(
            unix_date,
            "sms",
            event_extra=self._make_extra(
                old_day_of_week_mask,
                old_time_range,
                new_day_of_week_mask,
                new_time_range,
            ),
            amt=amt,
        )

    def incr_email(
        self,
        unix_date: int,
        *,
        old_day_of_week_mask: int,
        old_time_range: DailyReminderTimeRange,
        new_day_of_week_mask: int,
        new_time_range: DailyReminderTimeRange,
        amt: int = 1,
    ) -> None:
        """Increments the number of users which changed their daily reminder email settings"""
        self.incr_daily_reminder_settings(
            unix_date,
            "email",
            event_extra=self._make_extra(
                old_day_of_week_mask,
                old_time_range,
                new_day_of_week_mask,
                new_time_range,
            ),
            amt=amt,
        )

    def incr_push(
        self,
        unix_date: int,
        *,
        old_day_of_week_mask: int,
        old_time_range: DailyReminderTimeRange,
        new_day_of_week_mask: int,
        new_time_range: DailyReminderTimeRange,
        amt: int = 1,
    ) -> None:
        """Increments the number of users which changed their daily reminder push settings"""
        self.incr_daily_reminder_settings(
            unix_date,
            "push",
            event_extra=self._make_extra(
                old_day_of_week_mask,
                old_time_range,
                new_day_of_week_mask,
                new_time_range,
            ),
            amt=amt,
        )

    def incr_channel(
        self,
        unix_date: int,
        *,
        channel: Literal["sms", "email", "push"],
        old_day_of_week_mask: int,
        old_time_range: DailyReminderTimeRange,
        new_day_of_week_mask: int,
        new_time_range: DailyReminderTimeRange,
        amt: int = 1,
    ):
        if channel == "sms":
            self.incr_sms(
                unix_date,
                old_day_of_week_mask=old_day_of_week_mask,
                old_time_range=old_time_range,
                new_day_of_week_mask=new_day_of_week_mask,
                new_time_range=new_time_range,
                amt=amt,
            )
        elif channel == "email":
            self.incr_email(
                unix_date,
                old_day_of_week_mask=old_day_of_week_mask,
                old_time_range=old_time_range,
                new_day_of_week_mask=new_day_of_week_mask,
                new_time_range=new_time_range,
                amt=amt,
            )
        elif channel == "push":
            self.incr_push(
                unix_date,
                old_day_of_week_mask=old_day_of_week_mask,
                old_time_range=old_time_range,
                new_day_of_week_mask=new_day_of_week_mask,
                new_time_range=new_time_range,
                amt=amt,
            )
        else:
            assert False, channel


class daily_reminder_settings_stats:
    def __init__(self, itgs: Itgs) -> None:
        """An alternative simple interface for using DailyReminderSettingStatsPreparer stats which
        provides it as a context manager, storing it on exit.
        """
        self.itgs = itgs
        self.stats: Optional[DailyReminderSettingStatsPreparer] = None

    async def __aenter__(self) -> DailyReminderSettingStatsPreparer:
        assert self.stats is None
        self.stats = DailyReminderSettingStatsPreparer(RedisStatsPreparer())
        return self.stats

    async def __aexit__(self, *args) -> None:
        assert self.stats is not None
        await self.stats.stats.store(self.itgs)
        self.stats = None
