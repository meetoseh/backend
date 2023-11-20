import asyncio
from fastapi import APIRouter, Header
from pydantic import BaseModel, Field
from typing import Dict, List, Optional
import admin.lib.read_daily_stats as read_daily_stats
from lifespan import lifespan_handler
from models import STANDARD_ERRORS_BY_CODE


router = APIRouter()


class TouchLinkStats(BaseModel):
    labels: List[str] = Field(description="index-correspondant labels for all lists")

    created: List[int] = Field(
        description="how many buffered links were created by adding to the buffered link sorted set"
    )
    persist_queue_attempts: List[int] = Field(
        description="how many buffered links did we attempt to add to the persistable buffered link sorted set"
    )
    persist_queue_failed: List[int] = Field(
        description="of the persist queue attempts, how many did nothing"
    )
    persist_queue_failed_breakdown: Dict[str, List[int]] = Field(
        description="keys are already_queued/persisting/not_in_buffer"
    )
    persists_queued: List[int] = Field(
        description="of the persist queue attempts, how many resulted in a new entry in the "
        "persistable buffered links set"
    )
    persists_queued_breakdown: Dict[str, List[int]] = Field(
        description="keys are page identifiers"
    )
    persisted: List[int] = Field(
        description="how many links did the persist link job persist to the database "
        "within a batch where every row succeeded"
    )
    persisted_breakdown: Dict[str, List[int]] = Field(
        description="keys are page identifiers"
    )
    persisted_in_failed_batch: List[int] = Field(
        description="how many links did the persist link job persist to the database "
        "within a batch where at least one row failed"
    )
    persists_failed: List[int] = Field(
        description="how many links did the persist link job remove from the "
        "persistable buffered links set but didn't actually persist"
    )
    persists_failed_breakdown: Dict[str, List[int]] = Field(
        description="keys are lost/integrity"
    )
    click_attempts: List[int] = Field(description="how many clicks were received")
    clicks_buffered: List[int] = Field(
        description="of the click attempts, how many were added to the buffered link clicks "
        "pseudo-set because the code was in the buffered link sorted set"
    )
    clicks_buffered_breakdown: Dict[str, List[int]] = Field(
        description="keys are `{track type}:{page identifier}:vis={visitor known}:user={user known}`"
    )
    clicks_direct_to_db: List[int] = Field(
        description="of the click attempts, how many were persisted directly to the database "
        "because the corresponding link was already persisted"
    )
    clicks_direct_to_db_breakdown: Dict[str, List[int]] = Field(
        description="keys are `{track type}:{page identifier}:vis={visitor known}:user={user known}`"
    )
    clicks_delayed: List[int] = Field(
        description="of the click attempts, how many were added to the delayed link clicks "
        "sorted set because the link was in the purgatory for the persist link job"
    )
    clicks_delayed_breakdown: Dict[str, List[int]] = Field(
        description="keys are `{track type}:{page identifier}:vis={visitor known}:user={user known}`"
    )
    clicks_failed: List[int] = Field(
        description="of the click attempts, how many were ignored"
    )
    clicks_failed_breakdown: Dict[str, List[int]] = Field(
        description="keys are one of `dne`, "
        "`post_login:{page_identifier}:parent_not_found`, or "
        "`post_login:{page_identifier}:{source}:parent_has_child` where source is `db` or `redis` "
        "describing where the parent was found. can also be `other:{text}` if the failure "
        "reason could not be properly determined due to an unexpected error"
    )
    persisted_clicks: List[int] = Field(
        description="how many clicks did the persist link job persist while persisting the "
        "associated links, in batches that completely succeeded"
    )
    persisted_clicks_breakdown: Dict[str, List[int]] = Field(
        description="keys are `{page_identifier}:{number of clicks}` where number of clicks is "
        "for that particular link"
    )
    persisted_clicks_in_failed_batch: List[int] = Field(
        description="how many clicks did the persist link job persist while persisting the "
        "associated links, in batches where at least one row failed"
    )
    persist_click_failed: List[int] = Field(
        description="how many clicks did the persist link job fail to persist to "
        "the database"
    )
    delayed_clicks_attempted: List[int] = Field(
        description="how many attempts were made to persist clicks in the delayed "
        "link clicks sorted set by the delayed click persist job"
    )
    delayed_clicks_persisted: List[int] = Field(
        description="how many clicks were persisted by the delayed click persist job"
    )
    delayed_clicks_persisted_breakdown: Dict[str, List[int]] = Field(
        description="keys are `{track type}:vis={visitor known}:user={user known}` or `in_failed_batch`"
    )
    delayed_clicks_delayed: List[int] = Field(
        description="how many clicks were delayed further by the delayed click persist job "
        "because the link was still in the purgatory for the persist link job"
    )
    delayed_clicks_failed: List[int] = Field(
        description="how many clicks were failed to be persisted by the delayed click persist job"
    )
    delayed_clicks_failed_breakdown: Dict[str, List[int]] = Field(
        description="keys are:\n"
        "- `lost`: the link for the click is nowhere to be found\n"
        "- `duplicate`: there is already a click with that uid in the database"
    )
    abandons_attempted: List[int] = Field(
        description="how many attempts were made to abandon links"
    )
    abandoned: List[int] = Field(description="how many links were abandoned")
    abandoned_breakdown: Dict[str, List[int]] = Field(
        description="keys are `{page_identifier}:{number of clicks}`"
    )
    abandon_failed: List[int] = Field(
        description="how many links were attempted to be abandoned but failed"
    )
    abandon_failed_breakdown: Dict[str, List[int]] = Field(
        description="keys are `dne` or `already_persisting`"
    )
    leaked: List[int] = Field(
        description="how many times did the leaked link detection job "
        "handle a buffered link that was sitting there a long time"
    )
    leaked_breakdown: Dict[str, List[int]] = Field(
        description="keys are `recovered`, `abandoned`, or `duplicate`"
    )


class PartialTouchLinkStatsItem(BaseModel):
    created: int = Field(0)
    persist_queue_attempts: int = Field(0)
    persist_queue_failed: int = Field(0)
    persist_queue_failed_breakdown: Dict[str, int] = Field(default_factory=dict)
    persists_queued: int = Field(0)
    persists_queued_breakdown: Dict[str, int] = Field(default_factory=dict)
    persisted: int = Field(0)
    persisted_breakdown: Dict[str, int] = Field(default_factory=dict)
    persisted_in_failed_batch: int = Field(0)
    persists_failed: int = Field(0)
    persists_failed_breakdown: Dict[str, int] = Field(default_factory=dict)
    click_attempts: int = Field(0)
    clicks_buffered: int = Field(0)
    clicks_buffered_breakdown: Dict[str, int] = Field(default_factory=dict)
    clicks_direct_to_db: int = Field(0)
    clicks_direct_to_db_breakdown: Dict[str, int] = Field(default_factory=dict)
    clicks_delayed: int = Field(0)
    clicks_delayed_breakdown: Dict[str, int] = Field(default_factory=dict)
    clicks_failed: int = Field(0)
    clicks_failed_breakdown: Dict[str, int] = Field(default_factory=dict)
    persisted_clicks: int = Field(0)
    persisted_clicks_breakdown: Dict[str, int] = Field(default_factory=dict)
    persisted_clicks_in_failed_batch: int = Field(0)
    persist_click_failed: int = Field(0)
    delayed_clicks_attempted: int = Field(0)
    delayed_clicks_persisted: int = Field(0)
    delayed_clicks_persisted_breakdown: Dict[str, int] = Field(default_factory=dict)
    delayed_clicks_delayed: int = Field(0)
    delayed_clicks_failed: int = Field(0)
    delayed_clicks_failed_breakdown: Dict[str, int] = Field(default_factory=dict)
    abandons_attempted: int = Field(0)
    abandoned: int = Field(0)
    abandoned_breakdown: Dict[str, int] = Field(default_factory=dict)
    abandon_failed: int = Field(0)
    abandon_failed_breakdown: Dict[str, int] = Field(default_factory=dict)
    leaked: int = Field(0)
    leaked_breakdown: Dict[str, int] = Field(default_factory=dict)


class PartialTouchLinkStats(BaseModel):
    today: PartialTouchLinkStatsItem = Field(
        default_factory=lambda: PartialTouchLinkStatsItem.model_validate({})
    )
    yesterday: PartialTouchLinkStatsItem = Field(
        default_factory=lambda: PartialTouchLinkStatsItem.model_validate({})
    )


route = read_daily_stats.create_daily_stats_route(
    read_daily_stats.ReadDailyStatsRouteArgs(
        table_name="touch_link_stats",
        basic_data_redis_key=lambda unix_date: f"stats:touch_links:daily:{unix_date}".encode(
            "ascii"
        ),
        extra_data_redis_key=lambda unix_date, event: f"stats:touch_links:daily:{unix_date}:extra:{event}".encode(
            "ascii"
        ),
        earliest_data_redis_key=b"stats:touch_links:daily:earliest",
        pubsub_redis_key=b"ps:stats:touch_links:daily",
        compressed_response_local_cache_key=lambda start_unix_date, end_unix_date: f"daily_touch_links:{start_unix_date}:{end_unix_date}".encode(
            "ascii"
        ),
        simple_fields=[
            "created",
            "persist_queue_attempts",
            "persisted_in_failed_batch",
            "click_attempts",
            "persisted_clicks_in_failed_batch",
            "persist_click_failed",
            "delayed_clicks_attempted",
            "delayed_clicks_delayed",
            "abandons_attempted",
        ],
        fancy_fields=[
            "persist_queue_failed",
            "persists_queued",
            "persisted",
            "persists_failed",
            "clicks_buffered",
            "clicks_direct_to_db",
            "clicks_delayed",
            "clicks_failed",
            "persisted_clicks",
            "delayed_clicks_persisted",
            "delayed_clicks_failed",
            "abandoned",
            "abandon_failed",
            "leaked",
        ],
        response_model=TouchLinkStats,
        partial_response_model=PartialTouchLinkStats,
    )
)


@router.get(
    "/daily_touch_link_stats",
    response_model=TouchLinkStats,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_daily_touch_links_stats(authorization: Optional[str] = Header(None)):
    """Reads daily touch link statistics from the database for the preceeding 90
    days, ending on the day before yesterday. This endpoint is aggressively
    cached, thus it's not generally necessary for the frontend to reduce
    requests beyond respecting the cache control headers.

    Requires standard authorization for an admin user.
    """
    return await route.handler(authorization)


@router.get(
    "/partial_touch_link_stats",
    response_model=PartialTouchLinkStats,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_partial_touch_link_stats(authorization: Optional[str] = Header(None)):
    """Reads the touch link statistics that may still change. This endpoint
    is not cached in order to give the latest result.

    Requires standard authorization for an admin user.
    """
    return await route.partial_handler(authorization)


_background_tasks = []


@lifespan_handler
async def register_background_tasks():
    task = asyncio.create_task(route.background_task())
    yield
