from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Optional
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
    num_messages_attempted: int = Field(
        description="How many messages did we attempt to send last time the job completed normally"
    )
    num_succeeded: int = Field(
        description="How many messages the Expo Push API accepted the last time the job completed normally"
    )
    num_failed_permanently: int = Field(
        description="How many messages the Expo Push API rejected permanently the last time the job completed normally"
    )
    num_failed_transiently: int = Field(
        description="How many messages the Expo Push API rejected transiently the last time the job completed normally"
    )
    num_in_purgatory: int = Field(
        description="How many messages are in purgatory (i.e, being processed by the send job right now)"
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
                b"stats:push_tickets:send_job",
                b"last_started_at",
                b"last_finished_at",
                b"last_running_time",
                b"last_num_messages_attempted",
                b"last_num_succeeded",
                b"last_num_failed_permanently",
                b"last_num_failed_transiently",
            )
            await pipe.llen(b"push:message_attempts:purgatory")
            result, purgatory_size = await pipe.execute()

        if result[0] is None or result[1] is None:
            return Response(status_code=404)

        return Response(
            content=ReadLastSendJobResponse(
                started_at=float(result[0]),
                finished_at=float(result[1]),
                running_time=float(result[2]),
                num_messages_attempted=int(result[3]),
                num_succeeded=int(result[4]),
                num_failed_permanently=int(result[5]),
                num_failed_transiently=int(result[6]),
                num_in_purgatory=int(purgatory_size),
            ).json(),
            status_code=200,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
        )
