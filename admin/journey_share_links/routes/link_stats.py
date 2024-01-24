import asyncio
from fastapi import APIRouter, Header
from pydantic import BaseModel, Field
from typing import Annotated, Dict, List, Optional
import admin.lib.read_daily_stats as read_daily_stats
from models import STANDARD_ERRORS_BY_CODE
from lifespan import lifespan_handler


router = APIRouter()


class JourneyShareLinkStats(BaseModel):
    labels: List[str] = Field(description="index-correspondant labels for all lists")
    created: List[int] = Field(description="the number of links created")
    created_breakdown: Dict[str, List[int]] = Field(
        description="goes to a json object breaking down\n"
        "`created` by the internal name of the journey subcategory assigned to the\n"
        "journey the link is for at the time the link was created"
    )
    reused: List[int] = Field(
        description="the number of links reused, i.e., where a\n"
        "user requests a link to a journey that they specifically recently requested\n"
        "a link for, so instead of creating a new one we returned the previous one"
    )
    reused_breakdown: Dict[str, List[int]] = Field(
        description="goes to a json object breaking down\n"
        "`reused` by the internal name of the journey subcategory assigned to the\n"
        "journey the link is for at the time the link was created"
    )
    view_hydration_requests: List[int] = Field(
        description="how many phase 1 (hydration)\n"
        "requests were received, i.e., how many times an http request to our website\n"
        "formatted appropriately for a share link was received"
    )
    view_hydrated: List[int] = Field(
        description="of the view hydration requests received,\n"
        "how many were processed, had a valid code, and filled with an external journey"
    )
    view_hydrated_breakdown: Dict[str, List[int]] = Field(
        description="goes to a json object breaking down\n"
        "`view_hydrated` by the internal name of the journey subcategory assigned to the\n"
        "journey the code was for at the time the view was hydrated"
    )
    view_hydration_rejected: List[int] = Field(
        description="of the view hydration requests\n"
        "received, how many were not processed, instead requiring the client to follow\n"
        "the code in a separate request. this is done when ratelimiting watermarks are\n"
        "met"
    )
    view_hydration_failed: List[int] = Field(
        description="of the view hydration requests\n"
        "received, how many were processed but had an invalid code"
    )
    view_hydration_failed_breakdown: Dict[str, List[int]] = Field(
        description="goes to a json object breaking\n"
        "down `view_hydration_failed` by `{ratelimiting_applies}`, where `ratelimiting_applies`\n"
        "is one of `novel_code` or `repeat_code`, where a `novel_code` is one we haven't recently\n"
        "seen a request for, and `repeat_code` is one we have recently seen a request for. since\n"
        "ratelimiting is primarily intended to make scanning codes more difficult, we only\n"
        "ratelimit novel codes"
    )
    view_client_confirmation_requests: List[int] = Field(
        description="how many phase 2 (confirmation)\n"
        "requests were received. for properly functioning clients, this only happens after view\n"
        "hydrated, but that cannot be enforced"
    )
    view_client_confirmation_requests_breakdown: Dict[str, List[int]] = Field(
        description="goes to a json\n"
        "object breaking down `view_client_confirmation_requests` by `{vis}:{user}` where\n"
        "`vis` is one of `vis_avail` or `vis_missing` and `user` is one of `user_avail`\n"
        "or `user_missing`, so e.g., the key might be `vis_avail:user_missing`. these\n"
        "refer to if a reasonable visitor header and valid authorization header were provided,\n"
        "respectively"
    )
    view_client_confirmed: List[int] = Field(
        description="of the view client confirmation requests\n"
        "received, how many were processed to either immediately or eventually set `confirmed_at`\n"
        "on the view"
    )
    view_client_confirmed_breakdown: Dict[str, List[int]] = Field(
        description="goes to a json object\n"
        "breaking down `view_client_confirmed` by `{store}[:{details}]` where details depends\n"
        "on the store, and store is one of:\n"
        "- `redis`: we were able to confirm the request by queueing the update\n"
        "in the appropriate job. details is one of\n"
        "- `in_purgatory`: we used the raced confirmations hash\n"
        "- `standard`: we mutated the pseudoset directly\n"
        "- `database`: we were able to confirm the request by checking the database\n"
        "for the view. details are omitted, so the breakdown is just `database`"
    )
    view_client_confirm_failed: List[int] = Field(
        description="of the view client confirmation\n"
        "requests received, how many did not result in changes to `confirmed_at`"
    )
    view_client_confirm_failed_breakdown: Dict[str, List[int]] = Field(
        description="goes to a json object\n"
        "breaking down `view_client_confirm_failed` by:\n"
        "- `redis:{details}`: we were able to fail the request using the redis transaction\n"
        "without contacting the database. details is one of:\n"
        "- `already_confirmed`: `confirmed_at` set in the pseudoset\n"
        "- `in_purgatory_but_invalid`: in to log purgatory, but link uid is not set\n"
        "- `in_purgatory_and_already_confirmed`: in to log purgatory and raced confirmations hash\n"
        "- `database:{details}`: we failed the request when we went to mutate the view in the database\n"
        "- `not_found`: no such view uid in the database\n"
        "- `already_confirmed`: the view was already confirmed in the database\n"
        "- `too_old`: the view was too old to confirm at this point"
    )
    view_client_follow_requests: List[int] = Field(
        description="how many phase 3 (api) requests\n"
        "were received. for properly functioning web clients, this only happens after\n"
        "view hydration rejected, but this cannot be enforced. this is also the only flow\n"
        "that would be used by native clients"
    )
    view_client_follow_requests_breakdown: Dict[str, List[int]] = Field(
        description="goes to a json object\n"
        "breaking down `view_client_follow_requests` by `{vis}:{user}` where `vis` is\n"
        "one of `vis_avail` or `vis_missing` and `user` is one of `user_avail` or\n"
        "`user_missing`, so e.g., the key might be `vis_avail:user_missing`. these\n"
        "refer to if a reasonable visitor header and valid authorization header were\n"
        "provided, respectively"
    )
    view_client_followed: List[int] = Field(
        description="of the view client follow requests\n"
        "received, how many were processed and resulted in returning an external journey"
    )
    view_client_followed_breakdown: Dict[str, List[int]] = Field(
        description="goes to a json object breaking\n"
        "down `view_client_followed` by the internal name of the journey subcategory assigned\n"
        "to the journey associated with the code at the time the journey was returned"
    )
    view_client_follow_failed: List[int] = Field(
        description="of the view client follow requests\n"
        "received, how many were not processed due to ratelimiting or were rejected due to\n"
        "a bad code"
    )
    view_client_follow_failed_breakdown: Dict[str, List[int]] = Field(
        description="goes to a json object breaking\n"
        "down `view_client_follow_failed` by:\n"
        "- `ratelimited:{category}`: we did not process the request due to ratelimiting,\n"
        "and the `category` is one of: `visitor:1m`, `visitor:10m`, `user:1m`, `user:10m`,\n"
        "`no_user:1m`, `no_user:10m`, `global:1m`, `global:10m` referring to which water\n"
        "mark was hit (where multiple, the first from this list is used)\n"
        "- `invalid:{ratelimiting applies}`: we processed the code but it was invalid,\n"
        "where `ratelimiting_applies` is one of `novel_code` or `repeat_code`\n"
        "- `server_error`: we failed to fetch the journey due to some sort of transient issue"
    )


class PartialJourneyShareLinkStatsItem(BaseModel):
    created: int = Field(0)
    created_breakdown: Dict[str, int] = Field(default_factory=dict)
    reused: int = Field(0)
    reused_breakdown: Dict[str, int] = Field(default_factory=dict)
    view_hydration_requests: int = Field(0)
    view_hydrated: int = Field(0)
    view_hydrated_breakdown: Dict[str, int] = Field(default_factory=dict)
    view_hydration_rejected: int = Field(0)
    view_hydration_failed: int = Field(0)
    view_hydration_failed_breakdown: Dict[str, int] = Field(default_factory=dict)
    view_client_confirmation_requests: int = Field(0)
    view_client_confirmation_requests_breakdown: Dict[str, int] = Field(
        default_factory=dict
    )
    view_client_confirmed: int = Field(0)
    view_client_confirmed_breakdown: Dict[str, int] = Field(default_factory=dict)
    view_client_confirm_failed: int = Field(0)
    view_client_confirm_failed_breakdown: Dict[str, int] = Field(default_factory=dict)
    view_client_follow_requests: int = Field(0)
    view_client_follow_requests_breakdown: Dict[str, int] = Field(default_factory=dict)
    view_client_followed: int = Field(0)
    view_client_followed_breakdown: Dict[str, int] = Field(default_factory=dict)
    view_client_follow_failed: int = Field(0)
    view_client_follow_failed_breakdown: Dict[str, int] = Field(default_factory=dict)


class PartialJourneyShareLinkStats(BaseModel):
    today: PartialJourneyShareLinkStatsItem = Field(
        default_factory=lambda: PartialJourneyShareLinkStatsItem.model_validate({})
    )
    yesterday: PartialJourneyShareLinkStatsItem = Field(
        default_factory=lambda: PartialJourneyShareLinkStatsItem.model_validate({})
    )


route = read_daily_stats.create_daily_stats_route(
    read_daily_stats.ReadDailyStatsRouteArgs(
        table_name="journey_share_link_stats",
        basic_data_redis_key=lambda unix_date: f"stats:journey_share_links:daily:{unix_date}".encode(
            "ascii"
        ),
        extra_data_redis_key=lambda unix_date, event: f"stats:journey_share_links:daily:{unix_date}:extra:{event}".encode(
            "ascii"
        ),
        earliest_data_redis_key=b"stats:journey_share_links:daily:earliest",
        pubsub_redis_key=b"ps:stats:journey_share_links:daily",
        compressed_response_local_cache_key=lambda start_unix_date, end_unix_date: f"daily_journey_share_links:{start_unix_date}:{end_unix_date}".encode(
            "ascii"
        ),
        simple_fields=["view_hydration_requests", "view_hydration_rejected"],
        fancy_fields=[
            "created",
            "reused",
            "view_hydrated",
            "view_hydration_failed",
            "view_client_confirmation_requests",
            "view_client_confirmed",
            "view_client_confirm_failed",
            "view_client_follow_requests",
            "view_client_followed",
            "view_client_follow_failed",
        ],
        sparse_fancy_fields=[],
        response_model=JourneyShareLinkStats,
        partial_response_model=PartialJourneyShareLinkStats,
    )
)


@router.get(
    "/journey_share_link_stats",
    response_model=JourneyShareLinkStats,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_journey_share_link_stats(
    authorization: Annotated[Optional[str], Header()] = None
):
    """Reads journey share link stats from the database for the preceeding 90
    days, ending before yesterday. This endpoint is aggressively
    cached, thus it's not generally necessary for the frontend to reduce
    requests beyond respecting the cache control headers.

    Requires standard authorization for an admin user.
    """
    return await route.handler(authorization)


@router.get(
    "/partial_journey_share_link_stats",
    response_model=PartialJourneyShareLinkStats,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_partial_journey_share_link_stats(
    authorization: Optional[str] = Header(None),
):
    """Reads the journey share link stats that may still change. This endpoint
    is not cached in order to give the latest result.

    Requires standard authorization for an admin user.
    """
    return await route.partial_handler(authorization)


@lifespan_handler
async def register_background_tasks():
    task = asyncio.create_task(route.background_task())
    yield
