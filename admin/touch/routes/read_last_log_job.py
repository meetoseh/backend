from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal, Optional
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE
from itgs import Itgs


router = APIRouter()


class ReadLastLogJobResponse(BaseModel):
    started_at: float = Field(
        description="The last time the job started, in seconds since the epoch"
    )
    finished_at: float = Field(
        description="The last time the job completed normally, in seconds since the epoch"
    )
    running_time: float = Field(
        description="How long the job took last time it finished normally, in seconds"
    )
    inserts: int = Field(description="how many rows we tried to insert")
    updates: int = Field(description="how many rows we tried to update")
    full_batch_inserts: int = Field(
        description="how many full batches we performed for inserts"
    )
    full_batch_updates: int = Field(
        description="how many full batches we performed for updates"
    )
    partial_batch_inserts: int = Field(
        description="how many partial batches we performed for inserts"
    )
    partial_batch_updates: int = Field(
        description="how many partial batches we performed for updates"
    )
    accepted_inserts: int = Field(description="how many rows were accepted for inserts")
    accepted_updates: int = Field(description="how many rows were accepted for updates")
    failed_inserts: int = Field(
        description="how many more rows we expected to insert compared to how many we actually inserted"
    )
    failed_updates: int = Field(
        description="how many more rows we expected to update compared to how many we actually updated"
    )
    stop_reason: Literal["list_exhausted", "time_exhausted", "signal"] = Field(
        description="Why the job finished, the last time it finished normally"
    )
    in_purgatory: int = Field(
        description="How many logs are in purgatory (i.e, being processed by the log job right now)"
    )


@router.get(
    "/last_log_job",
    responses={
        "404": {
            "description": "No log job has ever been run",
        },
        **STANDARD_ERRORS_BY_CODE,
    },
    response_model=ReadLastLogJobResponse,
)
async def read_last_log_job(authorization: Optional[str] = Header(None)):
    """Fetches information about the last log job. Note that `started_at` is updated
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
            await pipe.hmget(  # type: ignore
                b"stats:touch_log:log_job",  # type: ignore
                b"started_at",  # type: ignore
                b"finished_at",  # type: ignore
                b"running_time",  # type: ignore
                b"inserts",  # type: ignore
                b"updates",  # type: ignore
                b"full_batch_inserts",  # type: ignore
                b"full_batch_updates",  # type: ignore
                b"partial_batch_inserts",  # type: ignore
                b"partial_batch_updates",  # type: ignore
                b"accepted_inserts",  # type: ignore
                b"accepted_updates",  # type: ignore
                b"failed_inserts",  # type: ignore
                b"failed_updates",  # type: ignore
                b"stop_reason",  # type: ignore
            )
            await pipe.llen(b"touch:log_purgatory")  # type: ignore
            result, purgatory_size = await pipe.execute()

        if result[0] is None or result[1] is None:
            return Response(status_code=404)

        return Response(
            content=ReadLastLogJobResponse(
                started_at=float(result[0]),
                finished_at=float(result[1]),
                running_time=float(result[2]),
                inserts=int(result[3]),
                updates=int(result[4]),
                full_batch_inserts=int(result[5]),
                full_batch_updates=int(result[6]),
                partial_batch_inserts=int(result[7]),
                partial_batch_updates=int(result[8]),
                accepted_inserts=int(result[9]),
                accepted_updates=int(result[10]),
                failed_inserts=int(result[11]),
                failed_updates=int(result[12]),
                stop_reason=result[13].decode("ascii"),
                in_purgatory=purgatory_size,
            ).model_dump_json(),
            status_code=200,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
        )
