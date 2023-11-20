from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal, Optional
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE
from itgs import Itgs


router = APIRouter()


class ReadLastReceiptReconciliationResponse(BaseModel):
    started_at: float = Field(
        description="The last time the job started, in seconds since the epoch"
    )
    finished_at: float = Field(
        description="The last time the job completed normally, in seconds since the epoch"
    )
    running_time: float = Field(
        description="How long the job took last time it finished normally, in seconds"
    )
    stop_reason: Literal["list_exhausted", "time_exhausted", "signal"] = Field(
        description="Why the job stopped"
    )
    attempted: int = Field(
        description="How many message resource updates we tried to reconcile"
    )
    pending: int = Field(
        description="How many message resources were still in a pending state"
    )
    succeeded: int = Field(
        description="How many message resources were now in a successful state"
    )
    failed: int = Field(
        description="How many message resources were now in a failed state"
    )
    found: int = Field(
        description="Of those attempted, how many had a matching item in the receipt pending set"
    )
    updated: int = Field(
        description="Of those found, how many did we update to a new but still pending state"
    )
    duplicate: int = Field(
        description="Of those found, how many didn't need an update because they had the same "
        "state as before"
    )
    out_of_order: int = Field(
        description="Of those found, how many didn't need an update because we had newer "
        "information already"
    )
    removed: int = Field(
        description="Of those found, how many did we remove from the receipt pending set"
    )
    purgatory_size: int = Field(description="Size of the Event Queue purgatory")


@router.get(
    "/last_receipt_reconciliation_job",
    responses={
        "404": {
            "description": "No receipt reconciliation job has ever been run",
        },
        **STANDARD_ERRORS_BY_CODE,
    },
    response_model=ReadLastReceiptReconciliationResponse,
)
async def read_last_receipt_reconciliation_job(
    authorization: Optional[str] = Header(None),
):
    """Fetches information about the last sms receipt reconciliation job. Note that
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
                b"stats:sms:receipt_reconciliation_job",  # type: ignore
                b"started_at",  # type: ignore
                b"finished_at",  # type: ignore
                b"running_time",  # type: ignore
                b"stop_reason",  # type: ignore
                b"attempted",  # type: ignore
                b"pending",  # type: ignore
                b"succeeded",  # type: ignore
                b"failed",  # type: ignore
                b"found",  # type: ignore
                b"updated",  # type: ignore
                b"duplicate",  # type: ignore
                b"out_of_order",  # type: ignore
                b"removed",  # type: ignore
            )  # type: ignore
            await pipe.llen(b"sms:event:purgatory")  # type: ignore
            result, num_in_purgatory = await pipe.execute()

        if result[0] is None or result[1] is None:
            return Response(status_code=404)

        return Response(
            content=ReadLastReceiptReconciliationResponse(
                started_at=float(result[0]),
                finished_at=float(result[1]),
                running_time=float(result[2]),
                stop_reason=result[3].decode("utf-8")
                if isinstance(result[3], bytes)
                else result[3],
                attempted=int(result[4]),
                pending=int(result[5]),
                succeeded=int(result[6]),
                failed=int(result[7]),
                found=int(result[8]),
                updated=int(result[9]),
                duplicate=int(result[10]),
                out_of_order=int(result[11]),
                removed=int(result[12]),
                purgatory_size=num_in_purgatory,
            ).model_dump_json(),
            status_code=200,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
        )
