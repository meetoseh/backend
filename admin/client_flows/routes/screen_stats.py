import asyncio
from fastapi import APIRouter, Header
from pydantic import BaseModel, Field
from typing import Annotated, Dict, List, Optional
import admin.lib.read_daily_stats as read_daily_stats
from models import STANDARD_ERRORS_BY_CODE
from lifespan import lifespan_handler


router = APIRouter()


class ClientScreenStats(BaseModel):
    labels: List[str] = Field(description="index-correspondant labels for all lists")
    queued: List[int] = Field(
        description="the number of a times a screen was added to a\n"
        "users client screens queue. Note that because of client flows that `replace`\n"
        "not all of these are expected to actually ever get peeked."
    )
    queued_breakdown: Dict[str, List[int]] = Field(
        description="goes to a json object breaking down\n"
        "`queued` by the `{platform}:{slug}`, where platform is one of `ios`,\n"
        "`android`, `browser`, or `server`. This is `server` when we queue outside\n"
        "of a direct api request and the client platform otherwise. The slug is the\n"
        "slug of the screen that was queued."
    )
    peeked: List[int] = Field(
        description="the number of times a screen was returned by the\n"
        "server, i.e., would have resulted in an entry in `user_client_screens_log`.\n"
        "Note that not all of these were actually seen by clients; for that, you have\n"
        "to remove ones that triggered a `skip` when popped. Note that the peek operation\n"
        "may have been part of a pop (all pops also peek, but not all peeks pop)."
    )
    peeked_breakdown: Dict[str, List[int]] = Field(
        description="goes to a json object breaking down\n"
        "`peeked` by the `{platform}:{slug}`, where platform is one of `ios`,\n"
        "`android`, or `browser`. The slug is the slug of the screen that was\n"
        "peeked."
    )
    popped: List[int] = Field(
        description="the number of times a screen was popped by a\n"
        "client. Note that not every peek results in a pop (e.g., open the app and\n"
        "then close it results in 1 peek and no pops). Further, not every screen\n"
        "which is peeked is popped by a client (i.e., dequeues can result from just\n"
        "generic background cleanup). only counts if the screen jwt was valid and\n"
        "it didn't result in desync"
    )
    popped_breakdown: Dict[str, List[int]] = Field(
        description="goes to a json object breaking down\n"
        "`popped` by the `{platform}:{slug}`, where platform is one of `ios`,\n"
        "`android`, or `browser`."
    )
    traced: List[int] = Field(
        description="the number of times a screen had a trace event\n"
        "associated with it"
    )
    traced_breakdown: Dict[str, List[int]] = Field(
        description="goes to a json object breaking down\n"
        "`traced` by the `{platform}:{slug}`, where platform is one of `ios`,\n"
        "`android`, or `browser`."
    )


class PartialClientScreenStatsItem(BaseModel):
    queued: int = Field(0)
    queued_breakdown: Dict[str, int] = Field(default_factory=dict)
    peeked: int = Field(0)
    peeked_breakdown: Dict[str, int] = Field(default_factory=dict)
    popped: int = Field(0)
    popped_breakdown: Dict[str, int] = Field(default_factory=dict)
    traced: int = Field(0)
    traced_breakdown: Dict[str, int] = Field(default_factory=dict)


class PartialClientScreenStats(BaseModel):
    today: PartialClientScreenStatsItem = Field(
        default_factory=lambda: PartialClientScreenStatsItem.model_validate({})
    )
    yesterday: PartialClientScreenStatsItem = Field(
        default_factory=lambda: PartialClientScreenStatsItem.model_validate({})
    )


route = read_daily_stats.create_daily_stats_route(
    read_daily_stats.ReadDailyStatsRouteArgs(
        table_name="client_screen_stats",
        basic_data_redis_key=lambda unix_date: f"stats:client_screens:daily:{unix_date}".encode(
            "ascii"
        ),
        extra_data_redis_key=lambda unix_date, event: f"stats:client_screens:daily:{unix_date}:extra:{event}".encode(
            "ascii"
        ),
        earliest_data_redis_key=b"stats:client_screens:daily:earliest",
        pubsub_redis_key=b"ps:stats:client_screens:daily",
        compressed_response_local_cache_key=lambda start_unix_date, end_unix_date: f"daily_client_screens:{start_unix_date}:{end_unix_date}".encode(
            "ascii"
        ),
        simple_fields=[],
        fancy_fields=["queued", "peeked", "popped", "traced"],
        sparse_fancy_fields=[],
        response_model=ClientScreenStats,
        partial_response_model=PartialClientScreenStats,
    )
)


@router.get(
    "/client_screen_stats",
    response_model=ClientScreenStats,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_client_screen_stats(
    authorization: Annotated[Optional[str], Header()] = None
):
    """Reads client screen stats from the database for the preceeding 90
    days, ending before yesterday. This endpoint is aggressively
    cached, thus it's not generally necessary for the frontend to reduce
    requests beyond respecting the cache control headers.

    Requires standard authorization for an admin user.
    """
    return await route.handler(authorization)


@router.get(
    "/partial_client_screen_stats",
    response_model=PartialClientScreenStats,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_partial_client_screen_stats(
    authorization: Optional[str] = Header(None),
):
    """Reads the client screen stats that may still change. This endpoint
    is not cached in order to give the latest result.

    Requires standard authorization for an admin user.
    """
    return await route.partial_handler(authorization)


@lifespan_handler
async def register_background_tasks():
    task = asyncio.create_task(route.background_task())
    yield
