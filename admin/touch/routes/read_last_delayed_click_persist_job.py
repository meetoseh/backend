from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal, Optional
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE
from itgs import Itgs


router = APIRouter()


class ReadLastDelayedClickPersistJobResponse(BaseModel):
    started_at: float = Field(
        description="The last time the job started, in seconds since the epoch"
    )
    finished_at: float = Field(
        description="The last time the job completed normally, in seconds since the epoch"
    )
    running_time: float = Field(
        description="How long the job took last time it finished normally, in seconds"
    )
    attempted: int = Field(description="the number of attempts to persist clicks")
    persisted: int = Field(
        description="of those attempted, how many led to actually persisting a click"
    )
    delayed: int = Field(
        description="of those attempted, how many led to adding the click back to the "
        "delayed link clicks sorted set because the link for the click was still in the "
        "persist purgatory"
    )
    lost: int = Field(
        description="of those attempted, how many were dropped because there was no link "
        "with that code anywhere"
    )
    duplicate: int = Field(
        description="of those attempted, how many were dropped because a click with that "
        "uid was already in the database"
    )
    stop_reason: Literal["list_exhausted", "time_exhausted", "signal"] = Field(
        description="Why the job finished, the last time it finished normally"
    )


@router.get(
    "/last_delayed_click_persist_job",
    responses={
        "404": {
            "description": "No delayed click persist job has ever been run",
        },
        **STANDARD_ERRORS_BY_CODE,
    },
    response_model=ReadLastDelayedClickPersistJobResponse,
)
async def last_delayed_click_persist_job(
    authorization: Optional[str] = Header(None),
):
    """Fetches information about the last delayed click persist job. Note that `started_at`
    is updated independently of the other fields and may be referring to a
    different run than the other fields.

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response
        redis = await itgs.redis()
        result = await redis.hmget(
            b"stats:touch_links:delayed_clicks_persist_job",
            b"started_at",
            b"finished_at",
            b"running_time",
            b"attempted",
            b"persisted",
            b"delayed",
            b"lost",
            b"duplicate",
            b"stop_reason",
        )

        if result[0] is None or result[1] is None:
            return Response(status_code=404)

        return Response(
            content=ReadLastDelayedClickPersistJobResponse(
                started_at=float(result[0]),
                finished_at=float(result[1]),
                running_time=float(result[2]),
                attempted=int(result[3]),
                persisted=int(result[4]),
                delayed=int(result[5]),
                lost=int(result[6]),
                duplicate=int(result[7]),
                stop_reason=result[8].decode("utf-8"),
            ).json(),
            status_code=200,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
        )
