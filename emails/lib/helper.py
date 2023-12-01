from emails.lib.events import EmailEvent
from itgs import Itgs
from redis_helpers.run_with_prep import run_with_prep
import unix_dates
import pytz
from redis_helpers.set_if_lower import ensure_set_if_lower_script_exists, set_if_lower


async def handle_event(itgs: Itgs, event: EmailEvent):
    """Queues the given email event to the email event queue, updating the
    webhook stats for the day as well
    """
    today = unix_dates.unix_timestamp_to_unix_date(
        event.received_at, tz=pytz.timezone("America/Los_Angeles")
    )
    webhook_stats_key = f"stats:email_webhooks:daily:{today}".encode("ascii")
    webhook_earliest_key = b"stats:email_webhooks:daily:earliest"
    event_queue_key = b"email:event"

    enc_event = event.__pydantic_serializer__.to_json(event)

    redis = await itgs.redis()

    async def prepare(force: bool):
        await ensure_set_if_lower_script_exists(redis, force=force)

    async def execute():
        async with redis.pipeline() as pipe:
            pipe.multi()
            await set_if_lower(pipe, webhook_earliest_key, today)
            await pipe.hincrby(webhook_stats_key, b"received", 1)  # type: ignore
            await pipe.hincrby(webhook_stats_key, b"verified", 1)  # type: ignore
            await pipe.hincrby(webhook_stats_key, b"accepted", 1)  # type: ignore
            await pipe.rpush(event_queue_key, enc_event)  # type: ignore
            await pipe.execute()

    await run_with_prep(prepare, execute)
