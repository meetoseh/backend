from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal, Optional
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE
from itgs import Itgs


router = APIRouter()


class ReadLastReceiptStaleResponse(BaseModel):
    started_at: float = Field(
        description="The last time the job started, in seconds since the epoch"
    )
    finished_at: float = Field(
        description="The last time the job completed normally, in seconds since the epoch"
    )
    running_time: float = Field(
        description="How long the job took last time it finished normally, in seconds"
    )
    callbacks_queued: int = Field(description="How many failure callbacks were queued")
    stop_reason: Literal["list_exhausted", "time_exhausted", "signal"] = Field(
        description="Why the job stopped"
    )
    recovery_queue_size: int = Field(
        description="The current size of the receipt recovery queue"
    )


@router.get(
    "/last_receipt_stale_job",
    responses={
        "404": {
            "description": "No receipt stale detection job has ever been run",
        },
        **STANDARD_ERRORS_BY_CODE,
    },
    response_model=ReadLastReceiptStaleResponse,
)
async def read_last_receipt_stale_job(authorization: Optional[str] = Header(None)):
    """Fetches information about the last receipt stale detection job. Note that
    `started_at` is updated independently of the other fields and may be
    referring to a different run than the other fields.

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response
        redis = await itgs.redis()
        async with redis.pipeline(transaction=False) as pipe:
            await pipe.hmget(
                b"stats:sms:receipt_stale_job",  # type: ignore
                b"started_at",  # type: ignore
                b"finished_at",  # type: ignore
                b"running_time",  # type: ignore
                b"callbacks_queued",  # type: ignore
                b"stop_reason",  # type: ignore
            )  # type: ignore
            await pipe.llen(b"sms:recovery")  # type: ignore
            result, recovery_queue_size = await pipe.execute()

        if result[0] is None or result[1] is None:
            return Response(status_code=404)

        return Response(
            content=ReadLastReceiptStaleResponse(
                started_at=float(result[0]),
                finished_at=float(result[1]),
                running_time=float(result[2]),
                callbacks_queued=int(result[3]),
                stop_reason=result[4].decode("utf-8")
                if isinstance(result[4], bytes)
                else result[4],
                recovery_queue_size=recovery_queue_size,
            ).model_dump_json(),
            status_code=200,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
        )
