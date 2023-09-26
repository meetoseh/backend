from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal, Optional
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE
from itgs import Itgs


router = APIRouter()


class ReadLastPersistLinkJobResponse(BaseModel):
    started_at: float = Field(
        description="The last time the job started, in seconds since the epoch"
    )
    finished_at: float = Field(
        description="The last time the job completed normally, in seconds since the epoch"
    )
    running_time: float = Field(
        description="How long the job took last time it finished normally, in seconds"
    )
    attempted: int = Field(
        description="how many entries within the persistable buffered link sorted set were removed and attempted"
    )
    lost: int = Field(
        description="of those attempted, how many were not in the buffered link sorted set"
    )
    integrity_error: int = Field(
        description="of those attempted, how many couldn't we persist because there was some "
        "integrity error, e.g., the link already existed or the touch didn't exist"
    )
    persisted: int = Field(description="of those attempted, how many were persisted")
    persisted_without_clicks: int = Field(
        description="of those persisted, how many had no clicks"
    )
    persisted_with_one_click: int = Field(
        description="of those persisted, how many had one click"
    )
    persisted_with_multiple_clicks: int = Field(
        description="of those persisted, how many had multiple clicks"
    )
    stop_reason: Literal["list_exhausted", "time_exhausted", "signal"] = Field(
        description="Why the job finished, the last time it finished normally"
    )
    in_purgatory: int = Field(
        description="How many links are in purgatory (i.e, being processed by the persist link job right now)"
    )


@router.get(
    "/last_persist_link_job",
    responses={
        "404": {
            "description": "No persist link job has ever been run",
        },
        **STANDARD_ERRORS_BY_CODE,
    },
    response_model=ReadLastPersistLinkJobResponse,
)
async def read_last_persist_link_job(authorization: Optional[str] = Header(None)):
    """Fetches information about the last persist link job. Note that `started_at` is updated
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
                b"stats:touch_links:persist_link_job",
                b"started_at",
                b"finished_at",
                b"running_time",
                b"attempted",
                b"lost",
                b"integrity_error",
                b"persisted",
                b"persisted_without_clicks",
                b"persisted_with_one_click",
                b"persisted_with_multiple_clicks",
                b"stop_reason",
            )
            await pipe.zcard(b"touch_links:persist_purgatory")
            result, purgatory_size = await pipe.execute()

        if result[0] is None or result[1] is None:
            return Response(status_code=404)

        return Response(
            content=ReadLastPersistLinkJobResponse(
                started_at=float(result[0]),
                finished_at=float(result[1]),
                running_time=float(result[2]),
                attempted=int(result[3]),
                lost=int(result[4]),
                integrity_error=int(result[5]),
                persisted=int(result[6]),
                persisted_without_clicks=int(result[7]),
                persisted_with_one_click=int(result[8]),
                persisted_with_multiple_clicks=int(result[9]),
                stop_reason=result[10].decode("utf-8"),
                in_purgatory=purgatory_size,
            ).json(),
            status_code=200,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
        )
