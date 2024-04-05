from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal, Optional
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE
from itgs import Itgs


router = APIRouter()


class ReadLastSendJobResponse(BaseModel):
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
    attempted: int = Field(description="how many values from the queue were processed")
    lost: int = Field(
        description="of those attempted, how many referenced non-existent rows in user daily reminders"
    )
    stale: int = Field(
        description="of those attempted, how many were dropped because their score was more "
        "than a threshold before the job start time"
    )
    links: int = Field(
        description="how many links we created for the touches we created"
    )
    sms: int = Field(description="how many sms touches we created")
    push: int = Field(description="how many push touches we created")
    email: int = Field(description="how many email touches we created")
    swaps: int = Field(description="how many daily reminder swaps occurred")
    purgatory_size: int = Field(description="how many items are in the send purgatory")


@router.get(
    "/last_send_job",
    responses={
        "404": {
            "description": "No send job has ever been run",
        },
        **STANDARD_ERRORS_BY_CODE,
    },
    response_model=ReadLastSendJobResponse,
)
async def last_send_job(
    authorization: Optional[str] = Header(None),
):
    """Fetches information about the last send job. Note that `started_at`
    is updated independently of the other fields and may be referring to a
    different run than the other fields.

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response
        redis = await itgs.redis()
        async with redis.pipeline() as pipe:
            pipe.multi()
            await pipe.hmget(
                b"stats:daily_reminders:send_job",  # type: ignore
                b"started_at",  # type: ignore
                b"finished_at",  # type: ignore
                b"running_time",  # type: ignore
                b"stop_reason",  # type: ignore
                b"attempted",  # type: ignore
                b"lost",  # type: ignore
                b"stale",  # type: ignore
                b"links",  # type: ignore
                b"sms",  # type: ignore
                b"push",  # type: ignore
                b"email",  # type: ignore
                b"swaps",  # type: ignore
            )  # type: ignore
            await pipe.zcard(b"daily_reminders:send_purgatory")
            response = await pipe.execute()

        result = response[0]
        purgatory_size = int(response[1])
        if result[0] is None or result[1] is None:
            return Response(status_code=404)

        return Response(
            content=ReadLastSendJobResponse(
                started_at=float(result[0]),
                finished_at=float(result[1]),
                running_time=float(result[2]),
                stop_reason=result[3].decode("utf-8"),
                attempted=int(result[4]),
                lost=int(result[5]),
                stale=int(result[6]),
                links=int(result[7]),
                sms=int(result[8]),
                push=int(result[9]),
                email=int(result[10]),
                swaps=int(result[11]),
                purgatory_size=purgatory_size,
            ).model_dump_json(),
            status_code=200,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
        )
