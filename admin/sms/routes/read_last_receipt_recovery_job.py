from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal, Optional
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE
from itgs import Itgs


router = APIRouter()


class ReadLastReceiptRecoveryResponse(BaseModel):
    started_at: float = Field(
        description="The last time the job started, in seconds since the epoch"
    )
    finished_at: float = Field(
        description="The last time the job completed normally, in seconds since the epoch"
    )
    running_time: float = Field(
        description="How long the job took last time it finished normally, in seconds"
    )
    attempted: int = Field(description="how many message resources we tried to fetch")
    pending: int = Field(
        description="how many message resources were retrieved successfully but still "
        "had a pending status (like `sending`)"
    )
    succeeded: int = Field(
        description="how many message resources were retrieved successfully and had a "
        "good final status (like `sent`)"
    )
    failed: int = Field(
        description="how many message resources were retrieved successfully but had a "
        "bad final status (like `undelivered`)"
    )
    lost: int = Field(
        description="how many message resources couldn't be retrieved because no such "
        "message resource exists on Twilio"
    )
    permanent_error: int = Field(
        description="how many message resources couldn't be retrieved because of an "
        "error unlikely be resolved by retrying"
    )
    transient_error: int = Field(
        description="how many message resources couldn't be retrieved because of an "
        "error likely to be resolved by retrying"
    )
    stop_reason: Literal["list_exhausted", "time_exhausted", "signal"] = Field(
        description="Why the job stopped"
    )
    purgatory_size: int = Field(
        description="The number of sids the receipt recovery job is currently working on"
    )


@router.get(
    "/last_receipt_recovery_job",
    responses={
        "404": {
            "description": "No receipt recovery job has ever been run",
        },
        **STANDARD_ERRORS_BY_CODE,
    },
    response_model=ReadLastReceiptRecoveryResponse,
)
async def read_last_receipt_recovery_job(authorization: Optional[str] = Header(None)):
    """Fetches information about the last sms receipt recovery job. Note that
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
                b"stats:sms:receipt_recovery_job",
                b"started_at",
                b"finished_at",
                b"running_time",
                b"attempted",
                b"pending",
                b"succeeded",
                b"failed",
                b"lost",
                b"permanent_error",
                b"transient_error",
                b"stop_reason",
            )
            await pipe.llen(b"sms:recovery_purgatory")
            result, num_in_purgatory = await pipe.execute()

        if result[0] is None or result[1] is None:
            return Response(status_code=404)

        return Response(
            content=ReadLastReceiptRecoveryResponse(
                started_at=float(result[0]),
                finished_at=float(result[1]),
                running_time=float(result[2]),
                attempted=int(result[3]),
                pending=int(result[4]),
                succeeded=int(result[5]),
                failed=int(result[6]),
                lost=int(result[7]),
                permanent_error=int(result[8]),
                transient_error=int(result[9]),
                stop_reason=result[10].decode("utf-8")
                if isinstance(result[10], bytes)
                else result[10],
                purgatory_size=num_in_purgatory,
            ).json(),
            status_code=200,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
        )
