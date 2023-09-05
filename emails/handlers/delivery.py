from emails.lib.events import EmailDeliveryNotification, EmailEvent
from itgs import Itgs
from redis_helpers.run_with_prep import run_with_prep
import unix_dates
import pytz
from redis_helpers.set_if_lower import ensure_set_if_lower_script_exists, set_if_lower
import time


async def handle_delivery(itgs: Itgs, body_json: dict):
    """Handles the given verified email delivery from Amazon SES"""
    received_at = time.time()
    today = unix_dates.unix_timestamp_to_unix_date(
        received_at, tz=pytz.timezone("America/Los_Angeles")
    )
    webhook_stats_key = f"stats:email_webhooks:daily:{today}".encode("ascii")
    webhook_earliest_key = b"stats:email_webhooks:daily:earliest"
    event_queue_key = b"email:event"

    event = (
        EmailEvent(
            message_id=body_json["mail"]["messageId"],
            notification=EmailDeliveryNotification(
                notification_type="Delivery",
            ),
            received_at=time.time(),
        )
        .json()
        .encode("utf-8")
    )

    redis = await itgs.redis()

    async def prepare(force: bool):
        await ensure_set_if_lower_script_exists(redis, force=force)

    async def execute():
        async with redis.pipeline() as pipe:
            pipe.multi()
            await set_if_lower(pipe, webhook_earliest_key, today)
            await pipe.hincrby(webhook_stats_key, b"received", 1)
            await pipe.hincrby(webhook_stats_key, b"verified", 1)
            await pipe.hincrby(webhook_stats_key, b"accepted", 1)
            await pipe.rpush(event_queue_key, event)
            await pipe.execute()

    await run_with_prep(prepare, execute)
