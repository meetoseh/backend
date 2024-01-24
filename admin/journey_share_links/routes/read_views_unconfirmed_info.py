from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Annotated, Optional, Tuple, cast
from models import STANDARD_ERRORS_BY_CODE
from auth import auth_admin
from itgs import Itgs


class ReadViewsUnconfirmedInfoResponse(BaseModel):
    length: int = Field(
        description="How many views are in the `views_unconfirmed` sorted set"
    )
    lowest_score: Optional[float] = Field(
        description=(
            "If there is at least one item in the sorted set, its score, which "
            "corresponds to when it was added to the set in seconds since the epoch"
        )
    )


router = APIRouter()


@router.get(
    "/views_unconfirmed_info",
    response_model=ReadViewsUnconfirmedInfoResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_views_unconfirmed_info(
    authorization: Annotated[Optional[str], Header()] = None
):
    """Reads information about the journey share links Unconfirmed Views sorted set

    Requires standard authorization for an admin user
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        redis = await itgs.redis()
        async with redis.pipeline() as pipe:
            pipe.multi()
            await pipe.zcard(b"journey_share_links:views_unconfirmed")
            await pipe.zrange(
                b"journey_share_links:views_unconfirmed", 0, 0, withscores=True
            )
            [length, lowest_score] = await pipe.execute()

        length = cast(int, length)
        lowest_score_entry = cast(Optional[Tuple[bytes, float]], lowest_score)
        lowest_score = None if lowest_score_entry is None else lowest_score_entry[1]

        return Response(
            content=ReadViewsUnconfirmedInfoResponse.__pydantic_serializer__.to_json(
                ReadViewsUnconfirmedInfoResponse(
                    length=length,
                    lowest_score=lowest_score,
                )
            ),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=200,
        )
