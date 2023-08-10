from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Optional
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE
from itgs import Itgs


router = APIRouter()


class ReadLastCheckJobResponse(BaseModel):
    started_at: float = Field(
        description="The last time the job started, in seconds since the epoch"
    )
    finished_at: float = Field(
        description="The last time the job completed normally, in seconds since the epoch"
    )
    running_time: float = Field(
        description="How long the job took last time it finished normally, in seconds"
    )
    num_checked: int = Field(
        description="How many receipts were requested the last time it finished normally"
    )
    num_succeeded: int = Field(
        description="How many success receipts were received the last time it finished normally"
    )
    num_failed_permanently: int = Field(
        description="How many message attempts failed permanently the last time it finished normally"
    )
    num_failed_transiently: int = Field(
        description="How many message attempts failed transiently the last time it finished normally"
    )
    num_in_purgatory: int = Field(
        description="How many receipts are being fetched right now"
    )


@router.get(
    "/last_check_job",
    responses={
        "404": {
            "description": "No check job has ever been run",
        },
        **STANDARD_ERRORS_BY_CODE,
    },
    response_model=ReadLastCheckJobResponse,
)
async def read_last_check_job(authorization: Optional[str] = Header(None)):
    """Fetches information about the last push receipt check job. Note that
    `started_at` is updated independently of the other fields and may be
    referring to a different run than the other fields.

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
                b"stats:push_receipts:check_job",
                b"last_started_at",
                b"last_finished_at",
                b"last_running_time",
                b"last_num_checked",
                b"last_num_succeeded",
                b"last_num_failed_permanently",
                b"last_num_failed_transiently",
            )
            await pipe.llen(b"push:push_tickets:purgatory")
            result, num_in_purgatory = await pipe.execute()

        if result[0] is None or result[1] is None:
            return Response(status_code=404)

        return Response(
            content=ReadLastCheckJobResponse(
                started_at=float(result[0]),
                finished_at=float(result[1]),
                running_time=float(result[2]),
                num_checked=int(result[3]),
                num_succeeded=int(result[4]),
                num_failed_permanently=int(result[5]),
                num_failed_transiently=int(result[6]),
                num_in_purgatory=num_in_purgatory,
            ).json(),
            status_code=200,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
        )
