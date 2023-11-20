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
    attempted: int = Field(description="How many touches were attempted last time")
    touch_points: int = Field(
        description="How many distinct touch points were attempted"
    )
    attempted_sms: int = Field(description="Of those attempted, how many were for sms")
    reachable_sms: int = Field(
        description="Of those attempted, how many had a phone number for sms"
    )
    unreachable_sms: int = Field(
        description="Of those attempted, how many did not have a phone number for sms"
    )
    attempted_push: int = Field(
        description="Of those attempted, how many were for push"
    )
    reachable_push: int = Field(
        description="Of those attempted, how many had a push token for push"
    )
    unreachable_push: int = Field(
        description="Of those attempted, how many did not have a push token for push"
    )
    attempted_email: int = Field(
        description="Of those attempted, how many were for email"
    )
    reachable_email: int = Field(
        description="Of those attempted, how many had an email address for email"
    )
    unreachable_email: int = Field(
        description="Of those attempted, how many did not have an email address for email"
    )
    stale: int = Field(
        description="Of those attempted, how many skipped because they were in the queue too long"
    )
    stop_reason: Literal[
        "list_exhausted", "time_exhausted", "backpressure", "signal"
    ] = Field(description="Why the job finished, the last time it finished normally")
    in_purgatory: int = Field(
        description="How many touches are in purgatory (i.e, being processed by the send job right now)"
    )


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
async def read_last_send_job(authorization: Optional[str] = Header(None)):
    """Fetches information about the last send job. Note that `started_at` is updated
    independently of the other fields and may be referring to a different run than the
    other fields.

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response
        redis = await itgs.redis()
        async with redis.pipeline(transaction=False) as pipe:
            await pipe.hmget(
                b"stats:touch_send:send_job",  # type: ignore
                b"started_at",  # type: ignore
                b"finished_at",  # type: ignore
                b"running_time",  # type: ignore
                b"attempted",  # type: ignore
                b"touch_points",  # type: ignore
                b"attempted_sms",  # type: ignore
                b"reachable_sms",  # type: ignore
                b"unreachable_sms",  # type: ignore
                b"attempted_push",  # type: ignore
                b"reachable_push",  # type: ignore
                b"unreachable_push",  # type: ignore
                b"attempted_email",  # type: ignore
                b"reachable_email",  # type: ignore
                b"unreachable_email",  # type: ignore
                b"stale",  # type: ignore
                b"stop_reason",  # type: ignore
            )
            await pipe.llen(b"touch:send_purgatory")  # type: ignore
            result, purgatory_size = await pipe.execute()

        if result[0] is None or result[1] is None:
            return Response(status_code=404)

        return Response(
            content=ReadLastSendJobResponse(
                started_at=float(result[0]),
                finished_at=float(result[1]),
                running_time=float(result[2]),
                attempted=int(result[3]),
                touch_points=int(result[4]),
                attempted_sms=int(result[5]),
                reachable_sms=int(result[6]),
                unreachable_sms=int(result[7]),
                attempted_push=int(result[8]),
                reachable_push=int(result[9]),
                unreachable_push=int(result[10]),
                attempted_email=int(result[11]),
                reachable_email=int(result[12]),
                unreachable_email=int(result[13]),
                stale=int(result[14]),
                stop_reason=result[15].decode("ascii"),
                in_purgatory=purgatory_size,
            ).model_dump_json(),
            status_code=200,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
        )
