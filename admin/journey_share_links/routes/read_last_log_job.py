from typing import Annotated, List, Literal, Optional, cast
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from auth import auth_admin
from itgs import Itgs


class ReadLastLogJobResponse(BaseModel):
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
    attempted: int = Field(description="How many link views we attempted to persist")
    persisted: int = Field(description="How many link views we successfully persisted")
    partially_persisted: int = Field(
        description=(
            "How many link views we persisted but were missing at least one "
            "piece of auxilary information, e.g., a visitor uid was provided "
            "but there was no corresponding visitor in the visitors table"
        )
    )
    failed: int = Field(
        description="How many link views we failed to store because there was no matching link"
    )
    stop_reason: Literal["list_exhausted", "time_exhausted", "signal"] = Field(
        description="The reason the job stopped running"
    )
    purgatory_length: int = Field(
        description="the number of items in the views log purgatory"
    )
    raced_views_to_confirm_length: int = Field(
        description=(
            "The number of view confirmations that are stored "
            "in the views_to_confirm hash because the view was "
            "confirmed while the view was in the to log purgatory"
        )
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
    "/last_log_job",
    response_model=ReadLastLogJobResponse,
    responses={
        "404": {
            "description": "The job has never been run",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def read_last_log_job(authorization: Annotated[Optional[str], Header()] = None):
    """Reads information on the last journey share links log job.

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
                b"stats:journey_share_links:log_job",  # type: ignore
                [
                    b"started_at",
                    b"finished_at",
                    b"running_time",
                    b"attempted",
                    b"persisted",
                    b"partially_persisted",
                    b"failed",
                    b"stop_reason",
                ],
            )
            await pipe.scard(b"journey_share_links:views_log_purgatory")  # type: ignore
            await pipe.hlen(b"journey_share_links:views_to_confirm")  # type: ignore
            [raw_result, purgatory_length, raced_views_to_confirm_length] = await pipe.execute()  # type: ignore

        if raw_result[0] is None or raw_result[1] is None:
            return ERROR_NEVER_RUN_RESPONSE

        raw_result = cast(List[bytes], raw_result)
        purgatory_length = cast(int, purgatory_length)
        raced_views_to_confirm_length = cast(int, raced_views_to_confirm_length)
        return Response(
            content=ReadLastLogJobResponse.__pydantic_serializer__.to_json(
                ReadLastLogJobResponse(
                    started_at=float(raw_result[0]),
                    finished_at=float(raw_result[1]),
                    running_time=float(raw_result[2]),
                    attempted=int(raw_result[3]),
                    persisted=int(raw_result[4]),
                    partially_persisted=int(raw_result[5]),
                    failed=int(raw_result[6]),
                    stop_reason=cast(
                        Literal["list_exhausted", "time_exhausted", "signal"],
                        raw_result[7].decode("utf-8"),
                    ),
                    purgatory_length=purgatory_length,
                    raced_views_to_confirm_length=raced_views_to_confirm_length,
                ),
            ),
            status_code=200,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
