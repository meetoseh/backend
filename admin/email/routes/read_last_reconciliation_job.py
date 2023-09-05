from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal, Optional
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE
from itgs import Itgs


router = APIRouter()


class ReadLastReconciliationJobResponse(BaseModel):
    started_at: float = Field(
        description="The last time the job started, in seconds since the epoch"
    )
    finished_at: float = Field(
        description="The last time the job completed normally, in seconds since the epoch"
    )
    running_time: float = Field(
        description="How long the job took last time it finished normally, in seconds"
    )
    attempted: int = Field(description="How many events we tried to process")
    succeeded_and_found: int = Field(
        description="how many were delivery receipts for emails in the receipt pending set"
    )
    succeeded_but_abandoned: int = Field(
        description="how many were delivery receipts for emails not in the receipt pending set; unexpected"
    )
    bounced_and_found: int = Field(
        description="how many were bounce for emails in the receipt pending set"
    )
    bounced_but_abandoned: int = Field(
        description="how many were bounce for emails not in the receipt pending set; unexpected"
    )
    complaint_and_found: int = Field(
        description="how many were complaint for emails in the receipt pending set"
    )
    complaint_and_abandoned: int = Field(
        description="how many were complaint for emails not in the receipt pending set"
    )
    stop_reason: Literal["list_exhausted", "time_exhausted", "signal"] = Field(
        description="Why the job finished, the last time it finished normally"
    )
    in_purgatory: int = Field(
        description="How many events are in purgatory (i.e, being processed by the reconciliation job right now)"
    )


@router.get(
    "/last_reconciliation_job",
    responses={
        "404": {
            "description": "No reconciliation job has ever been run",
        },
        **STANDARD_ERRORS_BY_CODE,
    },
    response_model=ReadLastReconciliationJobResponse,
)
async def read_last_reconciliation_job(authorization: Optional[str] = Header(None)):
    """Fetches information about the last reconciliation job. Note that `started_at` is updated
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
                b"stats:email_events:reconciliation_job",
                b"started_at",
                b"finished_at",
                b"running_time",
                b"attempted",
                b"succeeded_and_found",
                b"succeeded_but_abandoned",
                b"bounced_and_found",
                b"bounced_but_abandoned",
                b"complaint_and_found",
                b"complaint_and_abandoned",
                b"stop_reason",
            )
            await pipe.llen(b"email:reconciliation_purgatory")
            result, purgatory_size = await pipe.execute()

        if result[0] is None or result[1] is None:
            return Response(status_code=404)

        return Response(
            content=ReadLastReconciliationJobResponse(
                started_at=float(result[0]),
                finished_at=float(result[1]),
                running_time=float(result[2]),
                attempted=int(result[3]),
                succeeded_and_found=int(result[4]),
                succeeded_but_abandoned=int(result[5]),
                bounced_and_found=int(result[6]),
                bounced_but_abandoned=int(result[7]),
                complaint_and_found=int(result[8]),
                complaint_and_abandoned=int(result[9]),
                stop_reason=result[10].decode("utf-8")
                if isinstance(result[10], bytes)
                else result[10],
                in_purgatory=purgatory_size,
            ).json(),
            status_code=200,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
        )
