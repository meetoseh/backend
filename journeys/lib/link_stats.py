"""This module provides functions for keeping journey share links up to date.
"""

from typing import Literal, Optional, Tuple, Union, cast

import pytz
from error_middleware import handle_warning
from itgs import Itgs
from lib.redis_stats_preparer import RedisStatsPreparer
from redis_helpers.run_with_prep import run_with_prep
from redis_helpers.share_links_handle_visitor_view import (
    ensure_share_links_handle_visitor_view_script_exists,
    share_links_handle_visitor_view,
)
from unix_dates import unix_timestamp_to_unix_date
from pydantic import BaseModel, Field


class ViewClientFollowFailedRatelimitedReason(BaseModel):
    reason: Literal["ratelimited"] = Field(default="ratelimited")
    category: Literal["visitor", "user", "no_user", "global"] = Field()
    duration: Literal["1m", "10m"] = Field()

    @property
    def event_extra(self) -> bytes:
        return f"{self.reason}:{self.category}:{self.duration}".encode("utf-8")


class ViewClientFollowFailedInvalidReason(BaseModel):
    reason: Literal["invalid"] = Field(default="invalid")
    ratelimiting_applies: bool = Field()

    @property
    def event_extra(self) -> bytes:
        return (
            b"invalid:novel_code"
            if self.ratelimiting_applies
            else b"invalid:repeat_code"
        )


class ViewClientFollowFailedServerErrorReason(BaseModel):
    reason: Literal["server_error"] = Field(default="server_error")

    @property
    def event_extra(self) -> bytes:
        return b"server_error"


ViewClientFollowFailedReason = Union[
    ViewClientFollowFailedRatelimitedReason,
    ViewClientFollowFailedInvalidReason,
    ViewClientFollowFailedServerErrorReason,
]
"""See docs/redis/keys.md for stats:journey_share_links:daily:{unix_date}:extra:{event}"""


class ViewClientConfirmedRedis(BaseModel):
    store: Literal["redis"] = Field(default="redis")
    details: Literal["in_purgatory", "standard"] = Field()

    @property
    def event_extra(self) -> bytes:
        return f"{self.store}:{self.details}".encode("utf-8")


class ViewClientConfirmedDatabase(BaseModel):
    store: Literal["database"] = Field(default="database")

    @property
    def event_extra(self) -> bytes:
        return b"database"


ViewClientConfirmedExtra = Union[ViewClientConfirmedRedis, ViewClientConfirmedDatabase]


class ViewClientConfirmFailedRedis(BaseModel):
    store: Literal["redis"] = Field(default="redis")
    details: Literal[
        "already_confirmed",
        "in_purgatory_but_invalid",
        "in_purgatory_and_already_confirmed",
    ] = Field()

    @property
    def event_extra(self) -> bytes:
        return f"{self.store}:{self.details}".encode("utf-8")


class ViewClientConfirmFailedDatabase(BaseModel):
    store: Literal["database"] = Field(default="database")
    details: Literal["not_found", "already_confirmed", "too_old"] = Field()

    @property
    def event_extra(self) -> bytes:
        return f"{self.store}:{self.details}".encode("utf-8")


ViewClientConfirmFailedExtra = Union[
    ViewClientConfirmFailedRedis, ViewClientConfirmFailedDatabase
]


class JourneyShareLinksStatsPreparer:
    def __init__(self, stats: RedisStatsPreparer) -> None:
        self.stats = stats

    def incr_share_link_stat(
        self,
        *,
        unix_date: int,
        event: str,
        event_extra: Optional[bytes] = None,
        amt: int = 1,
    ) -> None:
        self.stats.incrby(
            unix_date=unix_date,
            event=event,
            event_extra=event_extra,
            amt=amt,
            basic_key_format="stats:journey_share_links:daily:{unix_date}",
            earliest_key=b"stats:journey_share_links:daily:earliest",
            event_extra_format="stats:journey_share_links:daily:{unix_date}:extra:{event}",
        )

    def incr_created(
        self, *, unix_date: int, journey_subcategory_internal_name: str, amt: int = 1
    ):
        """Also increments stats:journey_share_links:links:count"""
        self.incr_share_link_stat(
            unix_date=unix_date,
            event="created",
            event_extra=journey_subcategory_internal_name.encode("utf-8"),
            amt=amt,
        )
        self.stats.incr_direct(b"stats:journey_share_links:links:count", amt=amt)

    def incr_reused(
        self, *, unix_date: int, journey_subcategory_internal_name: str, amt: int = 1
    ):
        self.incr_share_link_stat(
            unix_date=unix_date,
            event="reused",
            event_extra=journey_subcategory_internal_name.encode("utf-8"),
            amt=amt,
        )

    def incr_view_hydration_requests(self, *, unix_date: int, amt: int = 1):
        self.incr_share_link_stat(
            unix_date=unix_date, event="view_hydration_requests", amt=amt
        )

    def incr_view_hydrated(
        self, *, unix_date: int, journey_subcategory_internal_name: str, amt: int = 1
    ):
        """increments stats:journey_share_links:views:count as well"""
        self.incr_share_link_stat(
            unix_date=unix_date,
            event="view_hydrated",
            event_extra=journey_subcategory_internal_name.encode("utf-8"),
            amt=amt,
        )
        self.stats.incr_direct(b"stats:journey_share_links:views:count", amt=amt)

    def incr_view_hydration_rejected(self, *, unix_date: int, amt: int = 1):
        self.incr_share_link_stat(
            unix_date=unix_date,
            event="view_hydration_rejected",
            amt=amt,
        )

    def incr_view_hydration_failed(
        self, *, unix_date: int, ratelimiting_applies: bool, amt: int = 1
    ):
        self.incr_share_link_stat(
            unix_date=unix_date,
            event="view_hydration_failed",
            event_extra=b"novel_code" if ratelimiting_applies else b"repeat_code",
            amt=amt,
        )

    def incr_view_client_confirmation_requests(
        self,
        *,
        unix_date: int,
        visitor_provided: bool,
        user_provided: bool,
        amt: int = 1,
    ):
        vis = "vis_avail" if visitor_provided else "vis_missing"
        user = "user_avail" if user_provided else "user_missing"
        self.incr_share_link_stat(
            unix_date=unix_date,
            event="view_client_confirmation_requests",
            event_extra=f"{vis}:{user}".encode("utf-8"),
            amt=amt,
        )

    def incr_view_client_confirmed(
        self, *, unix_date: int, extra: ViewClientConfirmedExtra, amt: int = 1
    ):
        """does not increment stats:journey_share_links:unique_views:count - special
        logic is required. you can use incr_immediately_journey_share_link_unique_views
        """
        self.incr_share_link_stat(
            unix_date=unix_date,
            event="view_client_confirmed",
            event_extra=extra.event_extra,
            amt=amt,
        )

    def incr_view_client_confirm_failed(
        self, *, unix_date: int, extra: ViewClientConfirmFailedExtra, amt: int = 1
    ):
        self.incr_share_link_stat(
            unix_date=unix_date,
            event="view_client_confirm_failed",
            event_extra=extra.event_extra,
            amt=amt,
        )

    def incr_view_client_follow_requests(
        self,
        *,
        unix_date: int,
        visitor_provided: bool,
        user_provided: bool,
        amt: int = 1,
    ):
        vis = "vis_avail" if visitor_provided else "vis_missing"
        user = "user_avail" if user_provided else "user_missing"
        self.incr_share_link_stat(
            unix_date=unix_date,
            event="view_client_follow_requests",
            event_extra=f"{vis}:{user}".encode("utf-8"),
            amt=amt,
        )

    def incr_view_client_followed(
        self, *, unix_date: int, journey_subcategory_internal_name: str, amt: int = 1
    ):
        """also increments stats:journey_share_links:views:count

        requires special handling for stats:journey_share_links:unique_views:count -
        you can use incr_immediately_journey_share_link_unique_views
        """
        self.incr_share_link_stat(
            unix_date=unix_date,
            event="view_client_followed",
            event_extra=journey_subcategory_internal_name.encode("utf-8"),
            amt=amt,
        )
        self.stats.incr_direct(b"stats:journey_share_links:views:count", amt=amt)

    def incr_view_client_follow_failed(
        self, *, unix_date: int, reason: ViewClientFollowFailedReason, amt: int = 1
    ):
        self.incr_share_link_stat(
            unix_date=unix_date,
            event="view_client_follow_failed",
            event_extra=reason.event_extra,
            amt=amt,
        )

    def incr_ratelimiting(
        self,
        *,
        duration: Literal["1m", "10m"],
        at: int,
        category: str,
        expire_at: int,
        amt: int = 1,
    ):
        """This is not a typical incrby; it is intended for incrementing a ratelimiting
        key, which uses redis expiration to purge old ratelimits
        """
        key = f"journey_share_links:ratelimiting:{duration}:{at}:{category}".encode(
            "utf-8"
        )
        self.stats.incr_direct(key, amt=amt)
        self.stats.set_expiration(key, expire_at, on_duplicate="latest")

    async def incr_immediately_journey_share_link_unique_views(
        self,
        *,
        itgs: Itgs,
        unix_date: int,
        view_uid: str,
        visitor_uid: str,
        journey_subcategory_internal_name: str,
        code: str,
        sharer_sub: Optional[str],
    ) -> bool:
        """Uses the given redis itgs instance to increment the number of
        unique journey share link views for the given date. This will increment
        the value only if the visitor with the given uid has not seen a journey
        share link view for the given date.

        This also manages stats:journey_share_links:unique_views:earliest and
        will set the visitor_was_unique key in the view pseudoset hash for the
        view if the view is still in the view pseudoset.

        Returns whether the increment was performed.
        """
        redis = await itgs.redis()
        args: Tuple[int, bytes, bytes, bytes, Optional[bytes], bytes] = (
            unix_date,
            visitor_uid.encode("utf-8"),
            code.encode("utf-8"),
            journey_subcategory_internal_name.encode("utf-8"),
            sharer_sub.encode("utf-8") if sharer_sub is not None else None,
            view_uid.encode("utf-8"),
        )

        async def _prepare(force: bool):
            await ensure_share_links_handle_visitor_view_script_exists(
                redis, force=force
            )

        async def _execute():
            return await share_links_handle_visitor_view(redis, *args)

        res = await run_with_prep(_prepare, _execute)
        assert res is not None
        return res


async def incr_journey_share_link_created(
    itgs: Itgs, /, *, stats: RedisStatsPreparer, journey_uid: str, now: float
) -> None:
    """Stores that we created a new journey share link for the journey with
    the given uid, fetching any required ancillary information
    """
    journey_subcategory = await _get_subcategory_for_stats(
        itgs, journey_uid=journey_uid
    )

    JourneyShareLinksStatsPreparer(stats).incr_created(
        unix_date=unix_timestamp_to_unix_date(
            now, tz=pytz.timezone("America/Los_Angeles")
        ),
        journey_subcategory_internal_name=journey_subcategory,
    )


async def incr_journey_share_link_reused(
    itgs: Itgs, /, *, stats: RedisStatsPreparer, journey_uid: str, now: float
) -> None:
    """Stores that we reused a journey share link for the journey with
    the given uid, fetching any required ancillary information
    """
    journey_subcategory = await _get_subcategory_for_stats(
        itgs, journey_uid=journey_uid
    )

    JourneyShareLinksStatsPreparer(stats).incr_created(
        unix_date=unix_timestamp_to_unix_date(
            now, tz=pytz.timezone("America/Los_Angeles")
        ),
        journey_subcategory_internal_name=journey_subcategory,
    )


async def _get_subcategory_for_stats(itgs: Itgs, /, *, journey_uid: str) -> str:
    conn = await itgs.conn()
    cursor = conn.cursor("none")

    response = await cursor.execute(
        """
        SELECT
            journey_subcategories.internal_name 
        FROM journeys, journey_subcategories
        WHERE
            journeys.uid = ?
            AND journeys.journey_subcategory_id = journey_subcategories.id
        """,
        (journey_uid,),
    )
    if not response.results:
        await handle_warning(
            f"{__name__}:no_subcategory_found",
            f"Storing that we created a link for journey `{journey_uid}`, but could not "
            "determine the internal name for its subcategory",
        )
        return "(missing)"

    return cast(str, response.results[0][0])


class journey_share_link_stats:
    """Basic async context manager wrapper around JourneyShareLinksStatsPreparer"""

    def __init__(
        self, itgs: Itgs, /, *, stats: Optional[RedisStatsPreparer] = None
    ) -> None:
        self.itgs = itgs
        self.stats = RedisStatsPreparer() if stats is None else stats

    async def __aenter__(self) -> JourneyShareLinksStatsPreparer:
        return JourneyShareLinksStatsPreparer(self.stats)

    async def __aexit__(self, *args) -> None:
        await self.stats.store(self.itgs)
