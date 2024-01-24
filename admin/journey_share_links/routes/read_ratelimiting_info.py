import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Annotated, Dict, Iterable, List, Optional, Tuple, cast
from models import STANDARD_ERRORS_BY_CODE
from auth import auth_admin
from itgs import Itgs


class RatelimitingBucket(BaseModel):
    duration_name: str = Field(
        description="The human readable name for the duration of this bucket, e.g., 1m"
    )
    duration_seconds: int = Field(
        description="The number of seconds in the duration of this bucket"
    )
    category: str = Field(
        description="The ratelimiting category this bucket is for, e.g., invalid"
    )
    at: int = Field(
        description="the bucket's start time in seconds since the epoch divided by the duration"
    )
    start: int = Field(
        description="When this bucket starts at in seconds since the epoch"
    )
    end: int = Field(description="When this bucket ends at in seconds since the epoch")
    count: int = Field(description="How many requests have been made in this bucket")


class ReadRatelimitingInfoResponse(BaseModel):
    buckets_by_category_then_duration: Dict[
        str, Dict[str, List[RatelimitingBucket]]
    ] = Field(
        description=(
            "The ratelimiting buckets that would still be available. The outer dictionary "
            "is keyed by the ratelimiting category, then each inner dictionary is keyed "
            "by the duration name, e.g., 1m, then each list is in ascending order of "
            "start. This excludes user-specific and visitor-specific ratelimiting information "
            "for brevity"
        )
    )


router = APIRouter()
DURATIONS: List[Tuple[str, int]] = [("1m", 60), ("10m", 600)]
CATEGORIES: Iterable[str] = (
    "invalid",
    "invalid_confirmed",
    "invalid_confirmed_with_user",
)
BUCKET_EXPIRATION_TIME_SECONDS = 60 * 30
"""how long before we expect the bucket will have been expired already, in seconds
from the end of the bucket
"""


@router.get(
    "/ratelimiting_info",
    response_model=ReadRatelimitingInfoResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_ratelimiting_info(
    authorization: Annotated[Optional[str], Header()] = None
):
    """Reads information about the journey share links Unconfirmed Views sorted set

    Requires standard authorization for an admin user
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        request_at_float = time.time()
        request_at_int = int(request_at_float)

        redis = await itgs.redis()
        async with redis.pipeline(transaction=False) as pipe:
            for bucket in _iter_buckets(request_at_int):
                await pipe.get(
                    f"journey_share_links:ratelimiting:{bucket.duration_name}:{bucket.at}:{bucket.category}".encode(
                        "utf-8"
                    )
                )
            counts = cast(List[Optional[bytes]], await pipe.execute())

        buckets_by_category_then_duration: Dict[
            str, Dict[str, List[RatelimitingBucket]]
        ] = {}
        for index, bucket in enumerate(_iter_buckets(request_at_int)):
            bucket.count = int(counts[index] or 0)

            buckets_by_category = buckets_by_category_then_duration.get(bucket.category)
            if buckets_by_category is None:
                buckets_by_category = {}
                buckets_by_category_then_duration[bucket.category] = buckets_by_category

            buckets_by_duration = buckets_by_category.get(bucket.duration_name)
            if buckets_by_duration is None:
                buckets_by_duration = []
                buckets_by_category[bucket.duration_name] = buckets_by_duration

            buckets_by_duration.append(bucket)

        return Response(
            content=ReadRatelimitingInfoResponse.__pydantic_serializer__.to_json(
                ReadRatelimitingInfoResponse(
                    buckets_by_category_then_duration=buckets_by_category_then_duration
                )
            ),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )


def _iter_buckets(request_at: int):
    for category in CATEGORIES:
        for duration_name, duration_seconds in DURATIONS:
            current_bucket = request_at // duration_seconds
            buckets_until_expiration = (
                BUCKET_EXPIRATION_TIME_SECONDS // duration_seconds
            )

            for bucket_at in range(
                current_bucket - buckets_until_expiration, current_bucket + 1
            ):
                yield RatelimitingBucket(
                    duration_name=duration_name,
                    duration_seconds=duration_seconds,
                    category=category,
                    at=bucket_at,
                    start=bucket_at * duration_seconds,
                    end=(bucket_at + 1) * duration_seconds,
                    count=0,
                )
