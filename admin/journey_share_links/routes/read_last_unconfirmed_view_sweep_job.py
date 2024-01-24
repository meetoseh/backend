from typing import Annotated, List, Literal, Optional, Tuple, cast
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from auth import auth_admin
from itgs import Itgs


class ReadLastUnconfirmedViewSweepJobResponse(BaseModel):
    started_at: float = Field(
        description=(
            "Time when the job started, in seconds since the epoch. "
            "Updated independently of the other fields."
        )
    )
    finished_at: float = Field(
        description="Time when the job finished, in seconds since the epoch."
    )
    running_time: float = Field(description="How long the job took in seconds")
    found: int = Field(description="How many stale link views were looked at")
    removed: int = Field(
        description="How many stale link views were removed as they were for invalid codes"
    )
    queued: int = Field(
        description="How many stale link views were added to the To Log Queue"
    )
    stop_reason: Literal[
        "list_exhausted", "time_exhausted", "backpressure", "signal"
    ] = Field(description="The reason the job stopped running")
    unconfirmed_length: int = Field(
        description="How many views are in the unconfirmed view sorted set"
    )
    oldest_unconfirmed_at: Optional[float] = Field(
        description="If there is at least one view in the unconfirmed view sorted set, the lowest "
        "score in the set, which can be interpreted as the time the oldest view was created "
        "in seconds since the epoch"
    )


router = APIRouter()
ERROR_404_TYPES = Literal["never_run"]
ERROR_NEVER_RUN_RESPONSE = Response(
    status_code=404,
    content=StandardErrorResponse[ERROR_404_TYPES].__pydantic_serializer__.to_json(
        StandardErrorResponse[ERROR_404_TYPES](
            type="never_run",
            message="The job has never been run",
        )
    ),
    headers={"Content-Type": "application/json; charset=utf-8"},
)


@router.get(
    "/last_unconfirmed_view_sweep_job",
    response_model=ReadLastUnconfirmedViewSweepJobResponse,
    responses={
        "404": {
            "description": "The job has never been run",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def read_last_unconfirmed_view_sweep_job(
    authorization: Annotated[Optional[str], Header()] = None
):
    """Reads information on the last journey share links unconfirmed view sweep job.

    Note that `started_at` is updated when the job begins to run, then
    the other fields are updated within a transaction after the job completes.

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        redis = await itgs.redis()
        async with redis.pipeline(transaction=False) as pipe:
            await pipe.hmget(
                b"stats:journey_share_links:sweep_unconfirmed_job",  # type: ignore
                [
                    b"started_at",
                    b"finished_at",
                    b"running_time",
                    b"found",
                    b"removed",
                    b"queued",
                    b"stop_reason",
                ],
            )
            await pipe.zcard(b"journey_share_links:views_unconfirmed")  # type: ignore
            await pipe.zrange(
                b"journey_share_links:views_unconfirmed", 0, 0, withscores=True
            )
            [raw_result, unconfirmed_length, oldest_unconfirmed] = await pipe.execute()  # type: ignore

        if raw_result[0] is None or raw_result[1] is None:
            return ERROR_NEVER_RUN_RESPONSE

        raw_result = cast(List[bytes], raw_result)
        unconfirmed_length = cast(int, unconfirmed_length)
        oldest_unconfirmed = cast(List[Tuple[bytes, float]], oldest_unconfirmed)
        return Response(
            content=ReadLastUnconfirmedViewSweepJobResponse.__pydantic_serializer__.to_json(
                ReadLastUnconfirmedViewSweepJobResponse(
                    started_at=float(raw_result[0]),
                    finished_at=float(raw_result[1]),
                    running_time=float(raw_result[2]),
                    found=int(raw_result[3]),
                    removed=int(raw_result[4]),
                    queued=int(raw_result[5]),
                    stop_reason=cast(
                        Literal[
                            "list_exhausted", "time_exhausted", "signal", "backpressure"
                        ],
                        raw_result[6].decode("utf-8"),
                    ),
                    unconfirmed_length=unconfirmed_length,
                    oldest_unconfirmed_at=None
                    if not oldest_unconfirmed
                    else oldest_unconfirmed[0][1],
                ),
            ),
            status_code=200,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
