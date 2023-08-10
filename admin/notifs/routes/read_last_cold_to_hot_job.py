from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Optional
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE
from itgs import Itgs


router = APIRouter()


class ReadLastColdToHotJobResponse(BaseModel):
    started_at: float = Field(
        description="The last time the job started, in seconds since the epoch"
    )
    finished_at: float = Field(
        description="The last time the job completed normally, in seconds since the epoch"
    )
    running_time: float = Field(
        description="How long the job took last time it finished normally, in seconds"
    )
    num_moved: int = Field(
        description="How many messages were moved from the cold to hot set the last time the job completed normally"
    )


@router.get(
    "/last_cold_to_hot_job",
    responses={
        "404": {
            "description": "No cold to hot job has ever been run",
        },
        **STANDARD_ERRORS_BY_CODE,
    },
    response_model=ReadLastColdToHotJobResponse,
)
async def read_last_cold_to_hot_job(authorization: Optional[str] = Header(None)):
    """Fetches information about the last ticket cold to hot job. Note that
    `started_at` is updated independently of the other fields and may be
    referring to a different run than the other fields.

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        redis = await itgs.redis()
        result = await redis.hmget(
            b"stats:push_receipts:cold_to_hot_job",
            b"last_started_at",
            b"last_finished_at",
            b"last_running_time",
            b"last_num_moved",
        )

        if result[0] is None or result[1] is None:
            return Response(status_code=404)

        return Response(
            content=ReadLastColdToHotJobResponse(
                started_at=float(result[0]),
                finished_at=float(result[1]),
                running_time=float(result[2]),
                num_moved=int(result[3]),
            ).json(),
            status_code=200,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
        )
