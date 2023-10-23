from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal, Optional
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE
from itgs import Itgs
from loguru import logger


router = APIRouter()


class ReadLastDelayedEmailsJobResponse(BaseModel):
    started_at: float = Field(
        description="The last time the job started, in seconds since the epoch"
    )
    finished_at: float = Field(
        description="The last time the job completed normally, in seconds since the epoch"
    )
    running_time: float = Field(
        description="How long the job took last time it finished normally, in seconds"
    )
    attempted: int = Field(description="how many values from the queue were processed")
    moved: int = Field(
        description="how many values were moved to the email to send queue"
    )
    stop_reason: Literal[
        "list_exhausted", "time_exhausted", "backpressure", "signal"
    ] = Field(description="The reason the job finished")


@router.get(
    "/last_delayed_emails_job",
    responses={
        "404": {
            "description": "No Send Delayed Email Verification job has ever been run",
        },
        **STANDARD_ERRORS_BY_CODE,
    },
    response_model=ReadLastDelayedEmailsJobResponse,
)
async def read_last_delayed_emails_job(authorization: Optional[str] = Header(None)):
    """Fetches information about the last Send Delayed Email Verification job.
    Note that `started_at` is updated independently of the other fields and may
    be referring to a different run than the other fields.

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        redis = await itgs.redis()
        result = await redis.hmget(
            b"stats:sign_in_with_oseh:send_delayed_job",
            b"started_at",
            b"finished_at",
            b"running_time",
            b"attempted",
            b"moved",
            b"stop_reason",
        )
        logger.debug(f"send delayed job stats: {result=}")

        if result[0] is None or result[1] is None:
            return Response(status_code=404)

        return Response(
            content=ReadLastDelayedEmailsJobResponse(
                started_at=float(result[0]),
                finished_at=float(result[1]),
                running_time=float(result[2]),
                attempted=int(result[3]),
                moved=int(result[4]),
                stop_reason=result[5].decode("utf-8"),
            ).json(),
            status_code=200,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
        )
