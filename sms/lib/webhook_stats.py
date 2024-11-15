"""Assists with updating statistics related to receiving SMS webhooks from twilio
"""

from typing import Literal
from redis_helpers.run_with_prep import run_with_prep
from redis_helpers.set_if_lower import set_if_lower, ensure_set_if_lower_script_exists
import redis.asyncio
import unix_dates
import pytz
from itgs import Itgs

timezone = pytz.timezone("America/Los_Angeles")

# TODO: Once on python 3.11, use enum.StrEnum
# Documentation for these events is under `docs/db/stats/push_ticket_stats.md`
SMSWebhookStatsEvent = Literal[
    "received",
    "verified",
    "accepted",
    "unprocessable",
    "signature_missing",
    "signature_invalid",
    "body_read_error",
    "body_max_size_exceeded",
    "body_parse_error",
]

SMS_WEBHOOK_STATS_EVENTS = frozenset(
    (
        "received",
        "verified",
        "accepted",
        "unprocessable",
        "signature_missing",
        "signature_invalid",
        "body_read_error",
        "body_max_size_exceeded",
        "body_parse_error",
    )
)


async def increment_event(
    itgs: Itgs, *, event: SMSWebhookStatsEvent, now: float, amount: int = 1
) -> None:
    """Increments the count for the given event at the given time by one. This
    handles preparing the event, transaction handling, and retries.

    Args:
        itgs (Itgs): the integrations to (re)use
        event (PushTicketStatsEvent): the event to increment
        now (float): the time to increment the event at
        amount (int, optional): the amount to increment by. Defaults to 1.
    """
    redis = await itgs.redis()

    async def prep(force: bool):
        await prepare_increment_event(redis, force=force)

    async def func():
        async with redis.pipeline() as pipe:
            pipe.multi()
            await attempt_increment_event(redis, event=event, now=now, amount=amount)
            await pipe.execute()

    await run_with_prep(prep, func)


async def prepare_increment_event(client: redis.asyncio.Redis, *, force: bool = False):
    """Performs necessary work on the given client to prepare it to
    increment an sms webhook stats event. This has to be done outside of
    a pipeline, and generally only needs to be called directly if you
    want to call attempt_increment_event alongside other commands within
    the same pipeline. Otherwise, use `increment_event` instead.

    This does not guarrantee that the attempt will succeed, but it does
    make it possible. This loads the scripts which will be required, which
    could then be removed again before the attempt actually starts (such
    as due to certain types of redis failovers, an explicit script flush, etc).
    Should generally retry failures at least once to handle with script flush,
    but note that it's generally complicated to deal with a redis failover
    since redis uses a persistent connection (so just waiting won't help, and
    you can't exactly queue a job since they are queued in redis)

    Args:
        client (redis.asyncio.Redis): The client to prepare, must not
            be actively pipelining
        force (bool, optional): If True, will force the script to be loaded
            even if we have loaded it recently. Defaults to False.
    """
    await ensure_set_if_lower_script_exists(client, force=force)


async def attempt_increment_event(
    client: redis.asyncio.Redis,
    *,
    event: SMSWebhookStatsEvent,
    now: float,
    amount: int = 1,
) -> None:
    """Increments the given event within the given redis client. This does
    not require anything about the pipelining state of the client, however,
    it does assume certain scripts are loaded (as if via `prepare_increment_event`),
    and if they fail the commands will fail. In a pipelining context, this will
    mean the function call succeeds but the execute() call will fail, and changes
    at the time of increment and later (but not previous commands) will not be
    applied.

    Args:
        client (redis.asyncio.Redis): The client to increment on
        event (PushTicketStatsEvent): The event to increment
        now (float): The current time, in seconds since the epoch
        amount (int, optional): The amount to increment by. Defaults to 1.
    """
    if event not in SMS_WEBHOOK_STATS_EVENTS:
        raise ValueError(f"Invalid event: {event}")

    unix_date = unix_dates.unix_timestamp_to_unix_date(now, tz=timezone)
    await set_if_lower(client, b"stats:sms_webhooks:daily:earliest", unix_date)
    await client.hincrby(  # type: ignore
        f"stats:sms_webhooks:daily:{unix_date}".encode("ascii"),  # type: ignore
        event.encode("utf-8"),  # type: ignore
        amount,
    )
