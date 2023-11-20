import asyncio
from fastapi import APIRouter, Header
from pydantic import BaseModel, Field
from typing import Dict, List, Optional
import admin.lib.read_daily_stats as read_daily_stats
from lifespan import lifespan_handler
from models import STANDARD_ERRORS_BY_CODE


router = APIRouter()


class SiwoVerifyEmailStats(BaseModel):
    labels: List[str] = Field(description="index-correspondant labels for all lists")
    email_requested: List[int] = Field(
        description="how many verification emails were\n" "requested"
    )
    email_failed: List[int] = Field(
        description="how many verification emails did we\n" "refuse to send"
    )
    email_failed_breakdown: Dict[str, List[int]] = Field(
        description="a json object where the values\n"
        "are integer counts and the keys are `{reason}[:{details}]` (ex:\n"
        "`bad_jwt:missing` or `ratelimited`):\n"
        "- `bad_jwt` - the Sign in with Oseh JWT is missing or invalid. details are:\n"
        "- `missing` - the JWT is missing\n"
        "- `malformed` - could not be interpreted as a JWT\n"
        "- `incomplete` - the JWT is missing required claims\n"
        "- `signature` - the signature is invalid\n"
        "- `bad_iss` - the issuer does not match the expected value\n"
        "- `bad_aud` - the audience does not match the expected value\n"
        "- `expired` - the JWT is expired\n"
        "- `revoked` - the JWT has been revoked\n"
        "- `backpressure` - there are too many emails in the email to send queue\n"
        "- `ratelimited` - we have sent a verification email to the user recently"
    )
    email_succeeded: List[int] = Field(
        description="how many verification emails did we send"
    )
    verify_attempted: List[int] = Field(
        description="how many verifications by code were\n" "attempted"
    )
    verify_failed: List[int] = Field(
        description="how many verification codes were rejected"
    )
    verify_failed_breakdown: Dict[str, List[int]] = Field(
        description="a json object where the values\n"
        "are integer counts and the keys are `{reason}[:{details}]`"
    )
    verify_succeeded: List[int] = Field(
        description="how many verification codes were accepted"
    )
    verify_succeeded_breakdown: Dict[str, List[int]] = Field(
        description="a json object where the values are\n"
        "integer counts and the keys are:\n"
        "- `was_verified` - the sign in with oseh already had a verified email and thus this\n"
        "did not result in a change\n"
        "- `was_unverified` - the sign in with oseh identity previously had an unverified\n"
        "email and now has a verified email"
    )


class PartialSiwoVerifyEmailStatsItem(BaseModel):
    email_requested: int = Field(0)
    email_failed: int = Field(0)
    email_failed_breakdown: Dict[str, int] = Field(default_factory=dict)
    email_succeeded: int = Field(0)
    verify_attempted: int = Field(0)
    verify_failed: int = Field(0)
    verify_failed_breakdown: Dict[str, int] = Field(default_factory=dict)
    verify_succeeded: int = Field(0)
    verify_succeeded_breakdown: Dict[str, int] = Field(default_factory=dict)


class PartialSiwoVerifyEmailStats(BaseModel):
    today: PartialSiwoVerifyEmailStatsItem = Field(
        default_factory=lambda: PartialSiwoVerifyEmailStatsItem.model_validate({})
    )
    yesterday: PartialSiwoVerifyEmailStatsItem = Field(
        default_factory=lambda: PartialSiwoVerifyEmailStatsItem.model_validate({})
    )


route = read_daily_stats.create_daily_stats_route(
    read_daily_stats.ReadDailyStatsRouteArgs(
        table_name="siwo_verify_email_stats",
        basic_data_redis_key=lambda unix_date: f"stats:sign_in_with_oseh:verify_email:daily:{unix_date}".encode(
            "ascii"
        ),
        extra_data_redis_key=lambda unix_date, event: f"stats:sign_in_with_oseh:verify_email:daily:{unix_date}:extra:{event}".encode(
            "ascii"
        ),
        earliest_data_redis_key=b"stats:sign_in_with_oseh:verify_email:daily:earliest",
        pubsub_redis_key=b"ps:stats:sign_in_with_oseh:verify_email:daily",
        compressed_response_local_cache_key=lambda start_unix_date, end_unix_date: f"daily_siwo_verify_email:{start_unix_date}:{end_unix_date}".encode(
            "ascii"
        ),
        simple_fields=["email_requested", "email_succeeded", "verify_attempted"],
        fancy_fields=["email_failed", "verify_failed", "verify_succeeded"],
        response_model=SiwoVerifyEmailStats,
        partial_response_model=PartialSiwoVerifyEmailStats,
    )
)


@router.get(
    "/siwo_verify_email_stats",
    response_model=SiwoVerifyEmailStats,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_siwo_verify_email_stats(authorization: Optional[str] = Header(None)):
    """Reads siwo verify email stats from the database for the preceeding 90
    days, ending before yesterday. This endpoint is aggressively
    cached, thus it's not generally necessary for the frontend to reduce
    requests beyond respecting the cache control headers.

    Requires standard authorization for an admin user.
    """
    return await route.handler(authorization)


@router.get(
    "/partial_siwo_verify_email_stats",
    response_model=PartialSiwoVerifyEmailStats,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_partial_siwo_verify_email_stats(
    authorization: Optional[str] = Header(None),
):
    """Reads the siwo verify email stats that may still change. This endpoint
    is not cached in order to give the latest result.

    Requires standard authorization for an admin user.
    """
    return await route.partial_handler(authorization)


_background_tasks = []


@lifespan_handler
async def register_background_tasks():
    task = asyncio.create_task(route.background_task())
    yield
