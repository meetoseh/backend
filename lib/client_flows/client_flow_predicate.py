from pydantic import BaseModel, Field
from typing import Dict, Generic, Optional, TypeVar, cast
from typing_extensions import TypedDict
from itgs import Itgs
from lib.opt_in_groups import check_if_user_in_opt_in_group
from lib.sticky_random_groups import check_if_user_in_sticky_random_group
from resources.filter_item import FilterItemModel
import random
from dataclasses import dataclass
import pytz

import unix_dates
from users.lib.timezones import get_user_timezone


class ClientFlowPredicate(BaseModel):
    version: Optional[FilterItemModel[int]] = Field(
        None,
        description="the client-provided android version code they want to match",
    )
    time_in_queue: Optional[FilterItemModel[int]] = Field(
        None,
        description="How long the client flow screen has been in the queue. Always zero at trigger time.",
    )
    queued_at: Optional[FilterItemModel[int]] = Field(
        None,
        description="The timestamp of when the client flow screen was queued, in seconds since the epoch.",
    )
    account_age: Optional[FilterItemModel[int]] = Field(
        None,
        description="How long since the users account record was created, in seconds.",
    )
    account_created_at: Optional[FilterItemModel[int]] = Field(
        None,
        description="The timestamp of when the user's account was created, in seconds since the epoch.",
    )
    sticky_random_groups: Optional[Dict[str, FilterItemModel[int]]] = Field(
        None,
        description="For each key in this dictionary, a filter against a 1 if the user is in the sticky group with that name and 0 otherwise",
    )
    opt_in_groups: Optional[Dict[str, FilterItemModel[int]]] = Field(
        None,
        description="For each key in this dictionary, a filter against a 1 if the user is in the opt-in group with that name and 0 otherwise",
    )
    random_float: Optional[FilterItemModel[float]] = Field(
        None,
        description="A random float in the range [0, 1)",
    )
    last_journey_rating: Optional[FilterItemModel[int]] = Field(
        None,
        description="If the user rated the last journey they took, the rating they gave it:\n"
        "1 - loved, 2 - liked, 3 - disliked, 4 - hated",
    )
    journeys_today: Optional[FilterItemModel[int]] = Field(
        None, description="The number of journeys the user has taken today"
    )
    journal_entries_in_history_today: Optional[FilterItemModel[int]] = Field(
        None,
        description="The number of journal entries added to the users journal created today",
    )
    or_predicate: Optional["ClientFlowPredicate"] = Field(
        None,
        description="If this is not None, then this predicate is satisfied if either this predicate or the or_predicate is satisfied. Short-circuits, outside first",
    )


T = TypeVar("T")


@dataclass
class Wrapped(Generic[T]):
    """Basic wrapper to allow a consistent way to distinguish not knowing a
    value and a value being None
    """

    value: T


@dataclass
class CheckFlowPredicateContext:
    """Used for storing conditionally fetched data for checking a flow predicate,
    in case you need to check more predicates within the same request
    """

    user_tz: Optional[Wrapped[pytz.BaseTzInfo]] = None
    last_journey_rating: Optional[Wrapped[Optional[int]]] = None
    journeys_today: Optional[Wrapped[int]] = None
    journal_entries_in_history_today: Optional[Wrapped[int]] = None


class ClientFlowPredicateParams(TypedDict):
    """Convenience class for describing the keyword arguments to check_flow_predicate"""

    version: Optional[int]
    queued_at: int
    account_created_at: int
    now: int
    user_sub: str
    ctx: CheckFlowPredicateContext


async def check_flow_predicate(
    itgs: Itgs,
    rule: ClientFlowPredicate,
    /,
    *,
    version: Optional[int],
    queued_at: int,
    account_created_at: int,
    now: int,
    user_sub: str,
    ctx: CheckFlowPredicateContext,
) -> bool:
    left_result = await _check_flow_predicate_non_recursive(
        itgs,
        rule,
        version=version,
        queued_at=queued_at,
        account_created_at=account_created_at,
        now=now,
        user_sub=user_sub,
        ctx=ctx,
    )
    if left_result:
        return True

    if rule.or_predicate is not None:
        return await check_flow_predicate(
            itgs,
            rule.or_predicate,
            version=version,
            queued_at=queued_at,
            account_created_at=account_created_at,
            now=now,
            user_sub=user_sub,
            ctx=ctx,
        )

    return False


async def _check_flow_predicate_non_recursive(
    itgs: Itgs,
    rule: ClientFlowPredicate,
    /,
    *,
    version: Optional[int],
    queued_at: int,
    account_created_at: int,
    now: int,
    user_sub: str,
    ctx: CheckFlowPredicateContext,
) -> bool:
    """Checks if the given client flow rule matches the available information"""
    if rule.version is not None and not rule.version.to_result().check_constant(
        version
    ):
        return False
    if (
        rule.time_in_queue is not None
        and not rule.time_in_queue.to_result().check_constant(now - queued_at)
    ):
        return False
    if rule.queued_at is not None and not rule.queued_at.to_result().check_constant(
        queued_at
    ):
        return False
    if rule.account_age is not None and not rule.account_age.to_result().check_constant(
        now - account_created_at
    ):
        return False
    if (
        rule.account_created_at is not None
        and not rule.account_created_at.to_result().check_constant(account_created_at)
    ):
        return False
    if rule.sticky_random_groups is not None:
        for group_name, filter_item in rule.sticky_random_groups.items():
            in_group = await check_if_user_in_sticky_random_group(
                itgs,
                user_sub=user_sub,
                group_name=group_name,
                create_if_not_exists=True,
            )
            if not filter_item.to_result().check_constant(int(in_group)):
                return False
    if rule.opt_in_groups is not None:
        for group_name, filter_item in rule.opt_in_groups.items():
            in_group = await check_if_user_in_opt_in_group(
                itgs,
                user_sub=user_sub,
                group_name=group_name,
                create_if_not_exists=True,
            )
            if not filter_item.to_result().check_constant(int(in_group)):
                return False
    if rule.random_float is not None:
        val = random.random()
        if not rule.random_float.to_result().check_constant(val):
            return False
    if rule.last_journey_rating is not None:
        rating = await _get_last_journey_rating(itgs, user_sub=user_sub, ctx=ctx)
        if not rule.last_journey_rating.to_result().check_constant(rating):
            return False
    if rule.journeys_today is not None:
        journeys_today = await _get_journeys_today(
            itgs, user_sub=user_sub, now=now, ctx=ctx
        )
        if not rule.journeys_today.to_result().check_constant(journeys_today):
            return False
    if rule.journal_entries_in_history_today is not None:
        journal_entries_in_history_today = await _get_journal_entries_in_history_today(
            itgs, user_sub=user_sub, now=now, ctx=ctx
        )
        if not rule.journal_entries_in_history_today.to_result().check_constant(
            journal_entries_in_history_today
        ):
            return False
    return True


async def _get_last_journey_rating(
    itgs: Itgs,
    /,
    *,
    user_sub: str,
    ctx: CheckFlowPredicateContext,
) -> Optional[int]:
    """Gets the last journey rating by the given user, if they rated thet last
    journey they took. Returns the value in the ctx if it's already been fetched
    """
    if ctx.last_journey_rating is not None:
        return ctx.last_journey_rating.value

    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    response = await cursor.execute(
        """
WITH
user(id) AS (
    SELECT users.id FROM users WHERE users.sub = ?
),
last_journey(journey_id, taken_at) AS (
    SELECT 
        user_journeys.journey_id,
        user_journeys.created_at
    FROM user, user_journeys
    WHERE user_journeys.user_id = user.id
    ORDER BY user_journeys.created_at DESC
    LIMIT 1
)
SELECT
    journey_feedback.response
FROM journey_feedback, user, last_journey
WHERE
    journey_feedback.journey_id = last_journey.journey_id
    AND journey_feedback.created_at >= last_journey.taken_at
    AND journey_feedback.user_id = user.id
ORDER BY journey_feedback.created_at DESC
LIMIT 1
        """,
        (user_sub,),
    )
    if not response.results:
        ctx.last_journey_rating = Wrapped(None)
        return None

    rating = cast(int, response.results[0][0])
    ctx.last_journey_rating = Wrapped(rating)
    return rating


async def _get_journeys_today(
    itgs: Itgs, /, *, user_sub: str, now: int, ctx: CheckFlowPredicateContext
) -> int:
    """Determines the number of journeys the user has taken today"""
    user_tz = await _get_user_tz(itgs, user_sub=user_sub, ctx=ctx)
    user_unix_date_today = unix_dates.unix_timestamp_to_unix_date(now, tz=user_tz)

    conn = await itgs.conn()
    cursor = conn.cursor("weak")
    response = await cursor.execute(
        """
SELECT
    COUNT(*)
FROM users, user_journeys
WHERE
    users.sub = ?
    AND users.id = user_journeys.user_id
    AND user_journeys.created_at_unix_date = ?
        """,
        (user_sub, user_unix_date_today),
    )
    assert response.results, response
    journeys_today = cast(int, response.results[0][0])
    ctx.journeys_today = Wrapped(journeys_today)
    return journeys_today


async def _get_journal_entries_in_history_today(
    itgs: Itgs, /, *, user_sub: str, now: int, ctx: CheckFlowPredicateContext
) -> int:
    if ctx.journal_entries_in_history_today is not None:
        return ctx.journal_entries_in_history_today.value

    user_tz = await _get_user_tz(itgs, user_sub=user_sub, ctx=ctx)
    user_unix_date_today = unix_dates.unix_timestamp_to_unix_date(now, tz=user_tz)

    conn = await itgs.conn()
    cursor = conn.cursor("weak")
    response = await cursor.execute(
        """
SELECT
    COUNT(*)
FROM users, journal_entries
WHERE
    users.sub = ?
    AND users.id = journal_entries.user_id
    AND journal_entries.created_unix_date = ?
    AND (journal_entries.flags & 1) = 0
        """,
        (user_sub, user_unix_date_today),
    )
    assert response.results, response
    journal_entries_in_history_today = cast(int, response.results[0][0])
    ctx.journal_entries_in_history_today = Wrapped(journal_entries_in_history_today)
    return journal_entries_in_history_today


async def _get_user_tz(
    itgs: Itgs, /, *, user_sub: str, ctx: CheckFlowPredicateContext
) -> pytz.BaseTzInfo:
    """Determines the timezone of the user"""
    if ctx.user_tz is None:
        ctx.user_tz = Wrapped(await get_user_timezone(itgs, user_sub=user_sub))
    return ctx.user_tz.value
