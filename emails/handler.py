from fastapi import Response
from emails.handlers.bounce import handle_bounce
from emails.handlers.complaint import handle_complaint
from error_middleware import handle_error
from itgs import Itgs
from emails.handlers.delivery import handle_delivery
import unix_dates
import pytz
from redis_helpers.run_with_prep import run_with_prep
from redis_helpers.set_if_lower import ensure_set_if_lower_script_exists, set_if_lower


async def handle_notification(body_json: dict, topic_arn: str):
    """Handles the given verified notification from Amazon SES"""
    notification_type = body_json["notificationType"]
    async with Itgs() as itgs:
        try:
            if notification_type == "Delivery":
                await handle_delivery(itgs, body_json)
            elif notification_type == "Bounce":
                await handle_bounce(itgs, body_json)
            elif notification_type == "Complaint":
                await handle_complaint(itgs, body_json)
            else:
                raise NotImplementedError(
                    f"unknown notification type: {notification_type}"
                )
            return Response(status_code=202)
        except Exception as e:
            await handle_error(e)
            today = unix_dates.unix_date_today(tz=pytz.timezone("America/Los_Angeles"))
            key = f"stats:email_webhooks:daily:{today}".encode("ascii")
            earliest_key = b"stats:email_webhooks:daily:earliest"

            redis = await itgs.redis()

            async def prepare(force: bool):
                await ensure_set_if_lower_script_exists(redis, force=force)

            async def execute():
                async with redis.pipeline() as pipe:
                    pipe.multi()
                    await set_if_lower(pipe, earliest_key, today)
                    await pipe.hincrby(key, b"received", 1)
                    await pipe.hincrby(key, b"verified", 1)
                    await pipe.hincrby(key, b"unprocessable", 1)
                    await pipe.execute()

            await run_with_prep(prepare, execute)
            return Response(status_code=503)
