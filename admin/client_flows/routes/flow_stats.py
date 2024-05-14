import asyncio
from fastapi import APIRouter, Header
from pydantic import BaseModel, Field
from typing import Annotated, Dict, List, Optional
import admin.lib.read_daily_stats as read_daily_stats
from models import STANDARD_ERRORS_BY_CODE
from lifespan import lifespan_handler


router = APIRouter()


class ClientFlowStats(BaseModel):
    labels: List[str] = Field(description="index-correspondant labels for all lists")
    triggered: List[int] = Field(description="the number of client flows triggered")
    triggered_breakdown: Dict[str, List[int]] = Field(
        description="goes to a json object breaking down\n"
        "`triggered` by the `{platform}:{slug}:{verified}`, where platform is one of `ios`,\n"
        "`android`, `browser`, or `server`. The slug is the slug of the flow that was\n"
        "triggered. `verified` is either `True` or `False` and is False for the standard\n"
        "endpoint and True for endpoints which perform semantic validation of the flow\n"
        "parameters before triggering the flow."
    )
    replaced: List[int] = Field(
        description="Documents triggers that were replaced with other\n"
        "triggers due to e.g. validation issues. These flows are _not_ included in the\n"
        "`triggered` number."
    )
    replaced_breakdown: Dict[str, List[int]] = Field(
        description="goes to a json object breaking down\n"
        "`replaced` by the `{platform}:[{screen_slug}]:{og_slug}:{new_slug}`, where\n"
        "platform is one of `ios`, `android`, `browser`, or `server`. The `og_slug`\n"
        "is the slug of the trigger that was attempted and replaced. `new_slug` is\n"
        "the slug of the trigger that was used instead. `screen_slug` is the slug\n"
        "of the screen that was being popped when the trigger occurred and is\n"
        "blank if the trigger did not occur during a pop."
    )


class PartialClientFlowStatsItem(BaseModel):
    triggered: int = Field(0)
    triggered_breakdown: Dict[str, int] = Field(default_factory=dict)
    replaced: int = Field(0)
    replaced_breakdown: Dict[str, int] = Field(default_factory=dict)


class PartialClientFlowStats(BaseModel):
    today: PartialClientFlowStatsItem = Field(
        default_factory=lambda: PartialClientFlowStatsItem.model_validate({})
    )
    yesterday: PartialClientFlowStatsItem = Field(
        default_factory=lambda: PartialClientFlowStatsItem.model_validate({})
    )


route = read_daily_stats.create_daily_stats_route(
    read_daily_stats.ReadDailyStatsRouteArgs(
        table_name="client_flow_stats",
        basic_data_redis_key=lambda unix_date: f"stats:client_flows:daily:{unix_date}".encode(
            "ascii"
        ),
        extra_data_redis_key=lambda unix_date, event: f"stats:client_flows:daily:{unix_date}:extra:{event}".encode(
            "ascii"
        ),
        earliest_data_redis_key=b"stats:client_flows:daily:earliest",
        pubsub_redis_key=b"ps:stats:client_flows:daily",
        compressed_response_local_cache_key=lambda start_unix_date, end_unix_date: f"daily_client_flows:{start_unix_date}:{end_unix_date}".encode(
            "ascii"
        ),
        simple_fields=[],
        fancy_fields=["triggered", "replaced"],
        sparse_fancy_fields=[],
        response_model=ClientFlowStats,
        partial_response_model=PartialClientFlowStats,
    )
)


@router.get(
    "/client_flow_stats",
    response_model=ClientFlowStats,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_client_flow_stats(
    authorization: Annotated[Optional[str], Header()] = None
):
    """Reads client flow stats from the database for the preceeding 90
    days, ending before yesterday. This endpoint is aggressively
    cached, thus it's not generally necessary for the frontend to reduce
    requests beyond respecting the cache control headers.

    Requires standard authorization for an admin user.
    """
    return await route.handler(authorization)


@router.get(
    "/partial_client_flow_stats",
    response_model=PartialClientFlowStats,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_partial_client_flow_stats(
    authorization: Optional[str] = Header(None),
):
    """Reads the client flow stats that may still change. This endpoint
    is not cached in order to give the latest result.

    Requires standard authorization for an admin user.
    """
    return await route.partial_handler(authorization)


@lifespan_handler
async def register_background_tasks():
    task = asyncio.create_task(route.background_task())
    yield
