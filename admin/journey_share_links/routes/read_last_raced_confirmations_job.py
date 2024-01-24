from typing import Annotated, List, Literal, Optional, cast
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from auth import auth_admin
from itgs import Itgs


class ReadLastRacedConfirmationsResponse(BaseModel):
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
    attempted: int = Field(
        description="How many keys in the raced confirmations hash were checked"
    )
    not_ready: int = Field(
        description="Of those attempted, how many were skipped because either "
        "the key is still in the to log purgatory or it was very recently added "
        "to the raced confirmations hash, and we are allowing time for `visitor_was_unique`"
    )
    persisted: int = Field(
        description="Of those attempted, how many were persisted will all auxilary information"
    )
    partially_persisted: int = Field(
        description="Of those attempted, how many were persisted but were missing at least one "
        "piece of auxilary information, e.g., a visitor uid was provided "
        "but there was no corresponding visitor in the visitors table"
    )
    failed_did_not_exist: int = Field(
        description="Of those attempted, how many were failed because the link view did not exist"
    )
    failed_already_confirmed: int = Field(
        description="Of those attempted, how many were failed because the link view was already confirmed; "
        "note that this is not exceptional since SCAN generally can return duplicates"
    )
    stop_reason: Literal["list_exhausted", "time_exhausted", "signal"] = Field(
        description="The reason the job stopped running"
    )
    raced_confirmations_length: int = Field(
        description="the number of items in the raced confirmations hash"
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
    "/last_raced_confirmations_job",
    response_model=ReadLastRacedConfirmationsResponse,
    responses={
        "404": {
            "description": "The job has never been run",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def read_last_raced_confirmations_job(
    authorization: Annotated[Optional[str], Header()] = None
):
    """Reads information on the last journey share links raced confirmations
    sweep job.

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
                b"stats:journey_share_links:raced_confirmations_job",  # type: ignore
                [
                    b"started_at",
                    b"finished_at",
                    b"running_time",
                    b"attempted",
                    b"not_ready",
                    b"persisted",
                    b"partially_persisted",
                    b"failed_did_not_exist",
                    b"failed_already_confirmed",
                    b"stop_reason",
                ],
            )
            await pipe.hlen(b"journey_share_links:views_to_confirm")  # type: ignore
            [raw_result, raced_confirmations_length] = await pipe.execute()  # type: ignore

        if raw_result[0] is None or raw_result[1] is None:
            return ERROR_NEVER_RUN_RESPONSE

        raw_result = cast(List[bytes], raw_result)
        raced_confirmations_length = cast(int, raced_confirmations_length)
        return Response(
            content=ReadLastRacedConfirmationsResponse.__pydantic_serializer__.to_json(
                ReadLastRacedConfirmationsResponse(
                    started_at=float(raw_result[0]),
                    finished_at=float(raw_result[1]),
                    running_time=float(raw_result[2]),
                    attempted=int(raw_result[3]),
                    not_ready=int(raw_result[4]),
                    persisted=int(raw_result[5]),
                    partially_persisted=int(raw_result[6]),
                    failed_did_not_exist=int(raw_result[7]),
                    failed_already_confirmed=int(raw_result[8]),
                    stop_reason=cast(
                        Literal["list_exhausted", "time_exhausted", "signal"],
                        raw_result[9].decode("utf-8"),
                    ),
                    raced_confirmations_length=raced_confirmations_length,
                ),
            ),
            status_code=200,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
