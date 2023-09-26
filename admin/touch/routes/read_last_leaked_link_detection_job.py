from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal, Optional
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE
from itgs import Itgs


router = APIRouter()


class ReadLastLeakedLinkDetectionJobResponse(BaseModel):
    started_at: float = Field(
        description="The last time the job started, in seconds since the epoch"
    )
    finished_at: float = Field(
        description="The last time the job completed normally, in seconds since the epoch"
    )
    running_time: float = Field(
        description="How long the job took last time it finished normally, in seconds"
    )
    leaked: int = Field(
        description="How many leaked entries in the buffered link sorted set were detected"
    )
    recovered: int = Field(
        description="Of those leaked, how many could be recovered since their user touch was "
        "in the database, hence we could persist the link"
    )
    abandoned: int = Field(
        description="Of those leaked, how many could not be recovered since their user touch "
        "was not in the database, hence we abandoned the link"
    )
    stop_reason: Literal["list_exhausted", "time_exhausted", "signal"] = Field(
        description="Why the job finished, the last time it finished normally"
    )


@router.get(
    "/last_leaked_link_detection_job",
    responses={
        "404": {
            "description": "No leaked link detection job has ever been run",
        },
        **STANDARD_ERRORS_BY_CODE,
    },
    response_model=ReadLastLeakedLinkDetectionJobResponse,
)
async def read_last_leaked_link_detection_job(
    authorization: Optional[str] = Header(None),
):
    """Fetches information about the last leaked link detection job. Note that `started_at`
    is updated independently of the other fields and may be referring to a
    different run than the other fields.

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response
        redis = await itgs.redis()
        result = await redis.hmget(
            b"stats:touch_links:leaked_link_detection_job",
            b"started_at",
            b"finished_at",
            b"running_time",
            b"leaked",
            b"recovered",
            b"abandoned",
            b"stop_reason",
        )

        if result[0] is None or result[1] is None:
            return Response(status_code=404)

        return Response(
            content=ReadLastLeakedLinkDetectionJobResponse(
                started_at=float(result[0]),
                finished_at=float(result[1]),
                running_time=float(result[2]),
                leaked=int(result[3]),
                recovered=int(result[4]),
                abandoned=int(result[5]),
                stop_reason=result[6].decode("utf-8"),
            ).json(),
            status_code=200,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
        )
