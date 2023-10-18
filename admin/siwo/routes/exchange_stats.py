import asyncio
from fastapi import APIRouter, Header
from pydantic import BaseModel, Field
from typing import Dict, List, Optional
import admin.lib.read_daily_stats as read_daily_stats
from models import STANDARD_ERRORS_BY_CODE


router = APIRouter()


class SiwoExchangeStats(BaseModel):
    labels: List[str] = Field(description="index-correspondant labels for all lists")
    attempted: List[int] = Field(description="how many users requested the exchange")
    failed: List[int] = Field(description="how many exchanges were rejected")
    failed_breakdown: Dict[str, List[int]] = Field(
        description="a json object whose keys are integer\n"
        "counts and the keys are e.g. `bad_jwt:missing`:\n"
        "- `bad_jwt` - the Sign in with Oseh JWT is missing or invalid. details are:\n"
        "- `missing` - the JWT is missing\n"
        "- `malformed` - could not be interpreted as a JWT\n"
        "- `incomplete` - the JWT is missing required claims\n"
        "- `signature` - the signature is invalid\n"
        "- `bad_iss` - the issuer does not match the expected value\n"
        "- `bad_aud` - the audience does not match the expected value\n"
        "- `expired` - the JWT is expired\n"
        "- `revoked` - the JWT has been revoked\n"
        "- `integrity` - the corresponding sign in with oseh identity has been deleted"
    )
    succeeded: List[int] = Field(description="how many exchanges occurred")


class PartialSiwoExchangeStatsItem(BaseModel):
    attempted: int = Field(0)
    failed: int = Field(0)
    failed_breakdown: Dict[str, int] = Field(default_factory=dict)
    succeeded: int = Field(0)


class PartialSiwoExchangeStats(BaseModel):
    today: PartialSiwoExchangeStatsItem = Field(
        default_factory=PartialSiwoExchangeStatsItem
    )
    yesterday: PartialSiwoExchangeStatsItem = Field(
        default_factory=PartialSiwoExchangeStatsItem
    )


route = read_daily_stats.create_daily_stats_route(
    read_daily_stats.ReadDailyStatsRouteArgs(
        table_name="siwo_exchange_stats",
        basic_data_redis_key=lambda unix_date: f"stats:sign_in_with_oseh:exchange:daily:{unix_date}".encode(
            "ascii"
        ),
        extra_data_redis_key=lambda unix_date, event: f"stats:sign_in_with_oseh:exchange:daily:{unix_date}:extra:{event}".encode(
            "ascii"
        ),
        earliest_data_redis_key=b"stats:sign_in_with_oseh:exchange:daily:earliest",
        pubsub_redis_key=b"ps:stats:sign_in_with_oseh:exchange:daily",
        compressed_response_local_cache_key=lambda start_unix_date, end_unix_date: f"daily_siwo_exchange:{start_unix_date}:{end_unix_date}".encode(
            "ascii"
        ),
        simple_fields=["attempted", "succeeded"],
        fancy_fields=["failed"],
        response_model=SiwoExchangeStats,
        partial_response_model=PartialSiwoExchangeStats,
    )
)


@router.get(
    "/siwo_exchange_stats",
    response_model=SiwoExchangeStats,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_siwo_exchange_stats(authorization: Optional[str] = Header(None)):
    """Reads siwo exchange stats from the database for the preceeding 90
    days, ending before yesterday. This endpoint is aggressively
    cached, thus it's not generally necessary for the frontend to reduce
    requests beyond respecting the cache control headers.

    Requires standard authorization for an admin user.
    """
    return await route.handler(authorization)


@router.get(
    "/partial_siwo_exchange_stats",
    response_model=PartialSiwoExchangeStats,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_partial_siwo_exchange_stats(
    authorization: Optional[str] = Header(None),
):
    """Reads the siwo exchange stats that may still change. This endpoint
    is not cached in order to give the latest result.

    Requires standard authorization for an admin user.
    """
    return await route.partial_handler(authorization)


_background_tasks = []


@router.on_event("startup")
def register_background_tasks():
    _background_tasks.append(asyncio.create_task(route.background_task()))
