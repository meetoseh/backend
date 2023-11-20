from fastapi import APIRouter, Request
from emails.handler import handle_notification
import sns.router_utils
from itgs import Itgs
import pytz
import unix_dates
from redis_helpers.run_with_prep import run_with_prep
from redis_helpers.set_if_lower import ensure_set_if_lower_script_exists, set_if_lower


router = APIRouter()

REQUEST_TYPE_TO_EVENT = {
    "SignatureMissing": "signature_missing",
    "SignatureInvalid": "signature_invalid",
    "BodyReadError": "body_read_error",
    "BodyMaxSizeExceededError": "body_max_size_exceeded",
    "BodyParseError": "body_parse_error",
}


@router.post("/sns-mail", include_in_schema=False)
async def sns_mail(request: Request):
    result = await sns.router_utils.handle_raw_unconfirmed_sns(
        request, sns.router_utils.std_confirm_subscription_wrapper, handle_notification
    )

    if result.request_type == "Notification":
        return result.response
    elif result.request_type == "SubscriptionConfirmation":
        return result.response

    async with Itgs() as itgs:
        evt = REQUEST_TYPE_TO_EVENT.get(result.request_type, "body_parse_error")
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
                await pipe.hincrby(key, b"received", 1)  # type: ignore
                await pipe.hincrby(key, evt, 1)  # type: ignore
                await pipe.execute()

        await run_with_prep(prepare, execute)

    return result.response
