from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal, Optional
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE
from itgs import Itgs


router = APIRouter()


class ReadLastAssignTimeJobResponse(BaseModel):
    started_at: float = Field(
        description="The last time the job started, in seconds since the epoch"
    )
    finished_at: float = Field(
        description="The last time the job completed normally, in seconds since the epoch"
    )
    running_time: float = Field(
        description="How long the job took last time it finished normally, in seconds"
    )
    stop_reason: Literal[
        "list_exhausted", "time_exhausted", "signal", "backpressure"
    ] = Field(description="Why the job finished, the last time it finished normally")
    start_unix_date: int = Field(
        description="the unix date that iteration started on, inclusive"
    )
    end_unix_date: int = Field(
        description="the unix date that iteration ended on, inclusive"
    )
    unique_timezones: int = Field(
        description="how many unique timezones were handled across all dates"
    )
    pairs: int = Field(
        description="how many `(unix_date, timezone)` pairs were handled"
    )
    queries: int = Field(
        description="how many queries to `user_daily_reminders` were made"
    )
    attempted: int = Field(
        description="how many rows within `user_daily_reminders` we attempted to handle"
    )
    overdue: int = Field(
        description="of those attempted, how many could have been assigned a time "
        "before the job start time"
    )
    stale: int = Field(
        description="of those overdue, how many were dropped because their end time "
        "was more than a threshold before the job start time"
    )
    sms_queued: int = Field(
        description="how many sms daily reminders we queued for the send job"
    )
    push_queued: int = Field(
        description="how many push daily reminders we queued for the send job"
    )
    email_queued: int = Field(
        description="how many email daily reminders we queued for the send job"
    )


@router.get(
    "/last_assign_time_job",
    responses={
        "404": {
            "description": "No assign time job has ever been run",
        },
        **STANDARD_ERRORS_BY_CODE,
    },
    response_model=ReadLastAssignTimeJobResponse,
)
async def last_assign_time_job(
    authorization: Optional[str] = Header(None),
):
    """Fetches information about the last assign time job. Note that `started_at`
    is updated independently of the other fields and may be referring to a
    different run than the other fields.

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response
        redis = await itgs.redis()
        result = await redis.hmget(  # type: ignore
            b"stats:daily_reminders:assign_time_job",  # type: ignore
            b"started_at",  # type: ignore
            b"finished_at",  # type: ignore
            b"running_time",  # type: ignore
            b"stop_reason",  # type: ignore
            b"start_unix_date",  # type: ignore
            b"end_unix_date",  # type: ignore
            b"unique_timezones",  # type: ignore
            b"pairs",  # type: ignore
            b"queries",  # type: ignore
            b"attempted",  # type: ignore
            b"overdue",  # type: ignore
            b"stale",  # type: ignore
            b"sms_queued",  # type: ignore
            b"push_queued",  # type: ignore
            b"email_queued",  # type: ignore
        )

        if result[0] is None or result[1] is None:
            return Response(status_code=404)

        return Response(
            content=ReadLastAssignTimeJobResponse(
                started_at=float(result[0]),
                finished_at=float(result[1]),
                running_time=float(result[2]),
                stop_reason=result[3].decode("utf-8"),
                start_unix_date=int(result[4]),
                end_unix_date=int(result[5]),
                unique_timezones=int(result[6]),
                pairs=int(result[7]),
                queries=int(result[8]),
                attempted=int(result[9]),
                overdue=int(result[10]),
                stale=int(result[11]),
                sms_queued=int(result[12]),
                push_queued=int(result[13]),
                email_queued=int(result[14]),
            ).model_dump_json(),
            status_code=200,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
        )
