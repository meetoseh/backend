import asyncio
from fastapi import APIRouter, Header
from pydantic import BaseModel, Field
from typing import Dict, List, Optional
import admin.lib.read_daily_stats as read_daily_stats
from lifespan import lifespan_handler
from models import STANDARD_ERRORS_BY_CODE


router = APIRouter()


class SiwoAuthorizeStats(BaseModel):
    labels: List[str] = Field(description="index-correspondant labels for all lists")
    check_attempts: List[int] = Field(
        description="how many users attempted to check if an\n"
        "account existed with an email address"
    )
    check_failed: List[int] = Field(
        description="of the checks attempted, how many were\n"
        "rejected outright because of a bad client id, redirect url, csrf token, or\n"
        "because they provided an invalid email verification code"
    )
    check_failed_breakdown: Dict[str, List[int]] = Field()
    check_elevated: List[int] = Field(
        description="of the checks attempted, how many did the\n"
        "backend block with a request for an email verification code"
    )
    check_elevated_breakdown: Dict[str, List[int]] = Field()
    check_elevation_acknowledged: List[int] = Field(
        description="of the checks elevated, how\n"
        "many were acknowledged by the client, ie., they requested the verification\n"
        "email"
    )
    check_elevation_failed: List[int] = Field(
        description="of the check elevations\n"
        "acknowledged, how many did we explicitly block due to backpressure"
    )
    check_elevation_failed_breakdown: Dict[str, List[int]] = Field()
    check_elevation_succeeded: List[int] = Field(
        description="of the check elevations\n"
        "acknowledged, how many did we tell the client we sent them a code for (though\n"
        "that doesn't necessarily mean we sent an email)"
    )
    check_elevation_succeeded_breakdown: Dict[str, List[int]] = Field()
    check_succeeded: List[int] = Field(
        description="of the checks attempted, how many did we\n"
        "provide a Login JWT for"
    )
    check_succeeded_breakdown: Dict[str, List[int]] = Field()
    login_attempted: List[int] = Field(
        description="how many users attempted to exchange a\n"
        "Login JWT for a Sign in with Oseh JWT on an existing identity"
    )
    login_failed: List[int] = Field(
        description="of the logins attempted, how many were\n"
        "blocked because the account did not exist, the password was wrong, due to\n"
        "ratelimiting, or because the JWT was invalid"
    )
    login_failed_breakdown: Dict[str, List[int]] = Field()
    login_succeeded: List[int] = Field(
        description="of the logins attempted, how many did\n"
        "we provide a Sign in with Oseh JWT for"
    )
    login_succeeded_breakdown: Dict[str, List[int]] = Field()
    create_attempted: List[int] = Field(
        description="how many users attempted to exchange a\n"
        "Login JWT for a Sign in with Oseh JWT for a new identity"
    )
    create_failed: List[int] = Field(
        description="of the creates attempted, how many did we\n"
        "reject because of an integrity issue or because the JWT was invalid"
    )
    create_failed_breakdown: Dict[str, List[int]] = Field()
    create_succeeded: List[int] = Field(
        description="of the creates attempted, how many did\n"
        "we create a new identity and return a Sign in with Oseh JWT for"
    )
    create_succeeded_breakdown: Dict[str, List[int]] = Field()
    password_reset_attempted: List[int] = Field(
        description="how many users attempted to\n"
        "exchange a Login JWT for an email containing a password reset code being\n"
        "sent to the email of the corresponding identity"
    )
    password_reset_failed: List[int] = Field(
        description="of the password resets attempted,\n"
        "how many were blocked explicitly because the identity did not exist, the email\n"
        "is suppressed, due to ratelimiting, because the JWT was invalid, or because of\n"
        "an issue with the email templating server"
    )
    password_reset_failed_breakdown: Dict[str, List[int]] = Field()
    password_reset_confirmed: List[int] = Field(
        description="of the password resets\n"
        "attempted, how many did we tell the user we sent them an email. This does not\n"
        "guarrantee we actually sent them an email"
    )
    password_reset_confirmed_breakdown: Dict[str, List[int]] = Field()
    password_update_attempted: List[int] = Field(
        description="how many users attempted to\n"
        "exchange a reset password code to update the password of an identity and get a\n"
        "Sign in with Oseh JWT for that identity."
    )
    password_update_failed: List[int] = Field(
        description="of the password updates\n"
        "attempted, how many were blocked explicitly because the reset password code\n"
        "did not exist, the corresponding identity did not exist, the csrf token was\n"
        "invalid, or due to ratelimiting"
    )
    password_update_failed_breakdown: Dict[str, List[int]] = Field()
    password_update_succeeded: List[int] = Field(
        description="of the password updates\n"
        "attempted, how many resulted in an identity with an updated password and a\n"
        "sign in with oseh jwt for that identity being given to the client"
    )
    password_update_succeeded_breakdown: Dict[str, List[int]] = Field()


class PartialSiwoAuthorizeStatsItem(BaseModel):
    check_attempts: int = Field(0)
    check_failed: int = Field(0)
    check_failed_breakdown: Dict[str, int] = Field(default_factory=dict)
    check_elevated: int = Field(0)
    check_elevated_breakdown: Dict[str, int] = Field(default_factory=dict)
    check_elevation_acknowledged: int = Field(0)
    check_elevation_failed: int = Field(0)
    check_elevation_failed_breakdown: Dict[str, int] = Field(default_factory=dict)
    check_elevation_succeeded: int = Field(0)
    check_elevation_succeeded_breakdown: Dict[str, int] = Field(default_factory=dict)
    check_succeeded: int = Field(0)
    check_succeeded_breakdown: Dict[str, int] = Field(default_factory=dict)
    login_attempted: int = Field(0)
    login_failed: int = Field(0)
    login_failed_breakdown: Dict[str, int] = Field(default_factory=dict)
    login_succeeded: int = Field(0)
    login_succeeded_breakdown: Dict[str, int] = Field(default_factory=dict)
    create_attempted: int = Field(0)
    create_failed: int = Field(0)
    create_failed_breakdown: Dict[str, int] = Field(default_factory=dict)
    create_succeeded: int = Field(0)
    create_succeeded_breakdown: Dict[str, int] = Field(default_factory=dict)
    password_reset_attempted: int = Field(0)
    password_reset_failed: int = Field(0)
    password_reset_failed_breakdown: Dict[str, int] = Field(default_factory=dict)
    password_reset_confirmed: int = Field(0)
    password_reset_confirmed_breakdown: Dict[str, int] = Field(default_factory=dict)
    password_update_attempted: int = Field(0)
    password_update_failed: int = Field(0)
    password_update_failed_breakdown: Dict[str, int] = Field(default_factory=dict)
    password_update_succeeded: int = Field(0)
    password_update_succeeded_breakdown: Dict[str, int] = Field(default_factory=dict)


class PartialSiwoAuthorizeStats(BaseModel):
    today: PartialSiwoAuthorizeStatsItem = Field(
        default_factory=lambda: PartialSiwoAuthorizeStatsItem.model_validate({})
    )
    yesterday: PartialSiwoAuthorizeStatsItem = Field(
        default_factory=lambda: PartialSiwoAuthorizeStatsItem.model_validate({})
    )


route = read_daily_stats.create_daily_stats_route(
    read_daily_stats.ReadDailyStatsRouteArgs(
        table_name="siwo_authorize_stats",
        basic_data_redis_key=lambda unix_date: f"stats:sign_in_with_oseh:authorize:daily:{unix_date}".encode(
            "ascii"
        ),
        extra_data_redis_key=lambda unix_date, event: f"stats:sign_in_with_oseh:authorize:daily:{unix_date}:extra:{event}".encode(
            "ascii"
        ),
        earliest_data_redis_key=b"stats:sign_in_with_oseh:authorize:daily:earliest",
        pubsub_redis_key=b"ps:stats:sign_in_with_oseh:authorize:daily",
        compressed_response_local_cache_key=lambda start_unix_date, end_unix_date: f"daily_siwo_authorize:{start_unix_date}:{end_unix_date}".encode(
            "ascii"
        ),
        simple_fields=[
            "check_attempts",
            "check_elevation_acknowledged",
            "login_attempted",
            "create_attempted",
            "password_reset_attempted",
            "password_update_attempted",
        ],
        fancy_fields=[
            "check_failed",
            "check_elevated",
            "check_elevation_failed",
            "check_elevation_succeeded",
            "check_succeeded",
            "login_failed",
            "login_succeeded",
            "create_failed",
            "create_succeeded",
            "password_reset_failed",
            "password_reset_confirmed",
            "password_update_failed",
            "password_update_succeeded",
        ],
        response_model=SiwoAuthorizeStats,
        partial_response_model=PartialSiwoAuthorizeStats,
    )
)


@router.get(
    "/siwo_authorize_stats",
    response_model=SiwoAuthorizeStats,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_siwo_authorize_stats(authorization: Optional[str] = Header(None)):
    """Reads siwo authorize stats from the database for the preceeding 90
    days, ending before yesterday. This endpoint is aggressively
    cached, thus it's not generally necessary for the frontend to reduce
    requests beyond respecting the cache control headers.

    Requires standard authorization for an admin user.
    """
    return await route.handler(authorization)


@router.get(
    "/partial_siwo_authorize_stats",
    response_model=PartialSiwoAuthorizeStats,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_partial_siwo_authorize_stats(
    authorization: Optional[str] = Header(None),
):
    """Reads the siwo authorize stats that may still change. This endpoint
    is not cached in order to give the latest result.

    Requires standard authorization for an admin user.
    """
    return await route.partial_handler(authorization)


_background_tasks = []


@lifespan_handler
async def register_background_tasks():
    task = asyncio.create_task(route.background_task())
    yield
