from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Dict, Optional
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE
from itgs import Itgs
import unix_dates
import pytz


router = APIRouter()


class ProgressInfoForTimezoneAndDate(BaseModel):
    start_time: int = Field(
        description="the start_time of the last row we materialized"
    )
    uid: str = Field(description="the uid of the last row we materialized")
    finished: bool = Field(
        description="whether we have finished iterating over this timezone and date"
    )


class ReadProgressInfoResponse(BaseModel):
    earliest_unix_date: int = Field(
        description="the earliest unix date we are still iterating over"
    )

    progress_by_date_and_timezone: Dict[
        int, Dict[str, Optional[ProgressInfoForTimezoneAndDate]]
    ] = Field(
        description="a mapping from unix date to a mapping from timezone to progress info. "
        "A null means that the timezone is in the timezones to iterate for that date, but it "
        "has not been started yet."
    )


@router.get(
    "/progress_info",
    responses={
        "404": {
            "description": "Daily reminders progress not yet initialized",
        },
        **STANDARD_ERRORS_BY_CODE,
    },
    response_model=ReadProgressInfoResponse,
)
async def read_progress_info(
    authorization: Optional[str] = Header(None),
):
    """Fetches information about daily reminders progress. Note that the technique
    use means the fields could be inconsistent with each other if the progress is
    updated while this request is being processed.

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response
        redis = await itgs.redis()

        earliest_raw = await redis.get(b"daily_reminders:progress:earliest")
        if earliest_raw is None:
            return Response(status_code=404)

        earliest_unix_date = int(earliest_raw)
        end_unix_date = unix_dates.unix_date_today(
            tz=pytz.timezone("America/Los_Angeles")
        )

        progress_by_date_and_timezone = dict()

        for unix_date in range(earliest_unix_date, end_unix_date + 1):
            progress_by_timezone = dict()

            timezones_raw = await redis.zrange(
                f"daily_reminders:progress:timezones:{unix_date}".encode("ascii"), 0, -1
            )
            if len(timezones_raw) == 0:
                continue

            for timezone_raw in timezones_raw:
                timezone = timezone_raw.decode("utf-8")

                progress_raw = await redis.hmget(
                    f"daily_reminders:progress:{timezone}:{unix_date}".encode("utf-8"),
                    b"start_time",
                    b"uid",
                    b"finished",
                )

                if progress_raw[0] is None:
                    progress_by_timezone[timezone] = None
                else:
                    progress_by_timezone[timezone] = ProgressInfoForTimezoneAndDate(
                        start_time=int(progress_raw[0]),
                        uid=progress_raw[1].decode("utf-8"),
                        finished=bool(int(progress_raw[2])),
                    )

            progress_by_date_and_timezone[unix_date] = progress_by_timezone

        return Response(
            content=ReadProgressInfoResponse(
                earliest_unix_date=earliest_unix_date,
                progress_by_date_and_timezone=progress_by_date_and_timezone,
            ).json(),
            status_code=200,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
        )
