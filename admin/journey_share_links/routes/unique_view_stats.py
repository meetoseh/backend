import asyncio
from fastapi import APIRouter, Header
from pydantic import BaseModel, Field
from typing import Annotated, Dict, List, Optional
import admin.lib.read_daily_stats as read_daily_stats
from models import STANDARD_ERRORS_BY_CODE
from lifespan import lifespan_handler


router = APIRouter()


class JourneyShareLinkUniqueViews(BaseModel):
    labels: List[str] = Field(description="index-correspondant labels for all lists")
    unique_views: List[int] = Field(
        description="The number of unique views as measured\n"
        "via the cardinality of the unique visitors set"
    )
    by_code: List[int] = Field(
        description="number of unique views for which a\n"
        "code is available (all of them)"
    )
    by_code_breakdown: Dict[str, Dict[int, int]] = Field(
        description="goes to a json object breaking\n"
        "down `by_code` by the code of the share link viewed\n"
        "\n"
        "This field is provided in a sparse format, i.e., rather than a list\n"
        "it is presented as a json object where the keys are the stringified\n"
        "0-based index and the values are the counts. Omitted keys have a\n"
        'count of 0. Ex: `{"0": 1, "3": 2}` is the same as `[1,0,0,2,0]`\n'
        "if the length of labels is 5"
    )
    by_journey_subcategory: List[int] = Field(
        description="number of unique views for\n"
        "which a journey subcategory internal name is available (all of them)"
    )
    by_journey_subcategory_breakdown: Dict[str, List[int]] = Field(
        description="goes to a json object\n"
        "breaking down `by_journey_subcategory` by the internal name of the journey subcategory\n"
        "for the journey associated with the code at the time the link was viewed"
    )
    by_sharer_sub: List[int] = Field(
        description="number of unique views for which\n"
        "the user who created the share link is still available (may be fewer than all of them\n"
        "due to deleted users)"
    )
    by_sharer_sub_breakdown: Dict[str, Dict[int, int]] = Field(
        description="goes to a json object\n"
        "breaking down `by_sharer_sub` by the sub of the user who created the link\n"
        "\n"
        "This field is provided in a sparse format, i.e., rather than a list\n"
        "it is presented as a json object where the keys are the stringified\n"
        "0-based index and the values are the counts. Omitted keys have a\n"
        'count of 0. Ex: `{"0": 1, "3": 2}` is the same as `[1,0,0,2,0]`\n'
        "if the length of labels is 5"
    )


class PartialJourneyShareLinkUniqueViewsItem(BaseModel):
    unique_views: int = Field(0)
    by_code: int = Field(0)
    by_code_breakdown: Dict[str, int] = Field(default_factory=dict)
    by_journey_subcategory: int = Field(0)
    by_journey_subcategory_breakdown: Dict[str, int] = Field(default_factory=dict)
    by_sharer_sub: int = Field(0)
    by_sharer_sub_breakdown: Dict[str, int] = Field(default_factory=dict)


class PartialJourneyShareLinkUniqueViews(BaseModel):
    today: PartialJourneyShareLinkUniqueViewsItem = Field(
        default_factory=lambda: PartialJourneyShareLinkUniqueViewsItem.model_validate(
            {}
        )
    )
    yesterday: PartialJourneyShareLinkUniqueViewsItem = Field(
        default_factory=lambda: PartialJourneyShareLinkUniqueViewsItem.model_validate(
            {}
        )
    )


route = read_daily_stats.create_daily_stats_route(
    read_daily_stats.ReadDailyStatsRouteArgs(
        table_name="journey_share_link_unique_views",
        basic_data_redis_key=lambda unix_date: f"stats:journey_share_links:unique_views:daily:{unix_date}".encode(
            "ascii"
        ),
        extra_data_redis_key=lambda unix_date, event: f"stats:journey_share_links:unique_views:daily:{unix_date}:extra:{event}".encode(
            "ascii"
        ),
        earliest_data_redis_key=b"stats:journey_share_links:unique_views:daily:earliest",
        pubsub_redis_key=b"ps:stats:journey_share_links:unique_views:daily",
        compressed_response_local_cache_key=lambda start_unix_date, end_unix_date: f"daily_journey_share_links:unique_views:{start_unix_date}:{end_unix_date}".encode(
            "ascii"
        ),
        simple_fields=["unique_views"],
        fancy_fields=["by_code", "by_journey_subcategory", "by_sharer_sub"],
        sparse_fancy_fields=["by_sharer_sub", "by_code"],
        response_model=JourneyShareLinkUniqueViews,
        partial_response_model=PartialJourneyShareLinkUniqueViews,
    )
)


@router.get(
    "/journey_share_link_unique_views",
    response_model=JourneyShareLinkUniqueViews,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_journey_share_link_unique_views(
    authorization: Annotated[Optional[str], Header()] = None
):
    """Reads journey share link unique views from the database for the preceeding 90
    days, ending before yesterday. This endpoint is aggressively
    cached, thus it's not generally necessary for the frontend to reduce
    requests beyond respecting the cache control headers.

    Requires standard authorization for an admin user.
    """
    return await route.handler(authorization)


@router.get(
    "/partial_journey_share_link_unique_views",
    response_model=PartialJourneyShareLinkUniqueViews,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_partial_journey_share_link_unique_views(
    authorization: Optional[str] = Header(None),
):
    """Reads the journey share link unique views that may still change. This endpoint
    is not cached in order to give the latest result.

    Requires standard authorization for an admin user.
    """
    return await route.partial_handler(authorization)


@lifespan_handler
async def register_background_tasks():
    task = asyncio.create_task(route.background_task())
    yield
