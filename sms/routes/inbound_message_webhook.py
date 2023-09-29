import io
from typing import List, Optional, Tuple
from fastapi import APIRouter
from fastapi.requests import Request
from fastapi.responses import Response
import hmac
from error_middleware import handle_error
from itgs import Itgs
import time
import os
import urllib.parse
import base64
from starlette.datastructures import URL
from loguru import logger
import secrets
import unix_dates
import pytz

from lib.daily_reminders.registration_stats import (
    DailyReminderRegistrationStatsPreparer,
)

router = APIRouter()


OPT_OUT_KEYWORDS = ("stop", "stopall", "unsubscribe", "cancel", "end", "quit")
OPT_IN_KEYWORDS = frozenset(("start", "yes", "unstop"))


@router.post("/inbound_webhook", include_in_schema=False)
async def inbound_message_webhook(request: Request):
    """Twilio inbound messages webhook endpoint; see also:

    - https://www.twilio.com/docs/usage/webhooks/sms-webhooks
    - https://www.twilio.com/docs/usage/webhooks/webhooks-security
    """
    async with Itgs() as itgs:
        if "x-twilio-signature" not in request.headers:
            logger.debug("Dropping inbound webhook; no x-twilio-signature provided")
            return Response(status_code=401)

        content_type = request.headers.get("content-type")
        if content_type is None:
            logger.debug("Dropping inbound webhook; no content-type provided")
            return Response(status_code=400)

        content_type_parts = [p.strip() for p in content_type.split(";", 2)]
        if content_type_parts[0] != "application/x-www-form-urlencoded":
            logger.debug(
                f"Dropping inbound webhook; wrong content type (a): {content_type=}"
            )
            return Response(status_code=400)

        if len(content_type_parts) not in (1, 2):
            logger.debug(
                f"Dropping inbound webhook; wrong content type (b): {content_type=}"
            )
            return Response(status_code=400)

        if len(content_type_parts) == 2:
            hint_parts = [p.strip() for p in content_type_parts[1].split("=", 2)]

            if len(hint_parts) != 2 or hint_parts[0] != "charset":
                logger.debug(
                    f"Dropping inbound webhook; wrong content type (c): {content_type=}"
                )
                return Response(status_code=400)

            if hint_parts[1] not in ("utf-8", "UTF-8", "utf8", "UTF8"):
                logger.debug(
                    f"Dropping inbound webhook; wrong content type (d): {content_type=}"
                )
                return Response(status_code=400)

        signature_b64: str = request.headers["x-twilio-signature"]
        try:
            signature: bytes = base64.b64decode(signature_b64)
        except:
            logger.debug(
                f"Dropping inbound webhook; failed to interpret signature as base64"
            )
            return Response(status_code=403)

        try:
            body_raw = io.BytesIO()
            async for chunk in request.stream():
                if body_raw.tell() + len(chunk) > 1024 * 1024:
                    logger.debug(f"Dropping inbound webhook; body too long")
                    return Response(status_code=413)
                body_raw.write(chunk)
        except:
            logger.exception(f"Dropping inbound webhook; error while loading body")
            return Response(status_code=500)

        body = body_raw.getvalue()
        if len(body) == 0:
            logger.debug(f"Dropping inbound webhook; body is empty")
            return Response(status_code=403)

        try:
            interpreted_body = urllib.parse.parse_qs(
                body.decode("utf-8"), keep_blank_values=True
            )
        except:
            logger.exception(f"Dropping inbound webhook; failed to parse body")
            return Response(status_code=400)

        if any(len(v) != 1 for v in interpreted_body.values()):
            logger.debug(f"Dropping inbound webhook; body contains duplicate keys")
            return Response(status_code=400)

        interpreted_body = {k: v[0] for k, v in interpreted_body.items()}

        base_url = URL(os.environ["ROOT_BACKEND_URL"])
        real_url = (
            URL(str(request.url))
            .replace(
                scheme=base_url.scheme, hostname=base_url.hostname, port=base_url.port
            )
            .components.geturl()
        )

        api_key = os.environ["OSEH_TWILIO_AUTH_TOKEN"]
        digest = hmac.new(api_key.encode("utf-8"), digestmod="SHA1")
        digest.update(real_url.encode("utf-8"))

        for key in sorted(interpreted_body.keys()):
            digest.update(key.encode("utf-8"))
            digest.update(interpreted_body[key].encode("utf-8"))

        expected_signature = digest.digest()

        if not hmac.compare_digest(expected_signature, signature):
            logger.debug(
                f"Dropping inbound webhook; wrong signature {real_url=} {interpreted_body=} {expected_signature=} {signature=}"
            )
            return Response(status_code=403)

        from_phone = interpreted_body.get("From")
        to_phone = interpreted_body.get("To")
        sms_body = interpreted_body.get("Body")
        opt_out_type = interpreted_body.get("OptOutType")

        try:
            assert isinstance(from_phone, str)
            assert isinstance(to_phone, str)
            assert isinstance(sms_body, str)
            assert opt_out_type in (None, "STOP", "HELP", "START")
        except Exception as e:
            await handle_error(
                e, extra_info=f"verified twilio inbound message {interpreted_body}"
            )

        sms_body_lower = sms_body.lower()
        is_opt_out = opt_out_type == "STOP" or any(
            kw in sms_body_lower for kw in OPT_OUT_KEYWORDS
        )
        is_opt_in = not is_opt_out and (
            opt_out_type == "START" or sms_body_lower in OPT_IN_KEYWORDS
        )
        response_sms_body = await handle_inbound_message(
            itgs, from_phone, to_phone, sms_body, is_opt_in, is_opt_out
        )
        if response_sms_body is None:
            return Response(status_code=204)

        return Response(
            content=f"<Response><Message>{response_sms_body}</Message></Response>".encode(
                "utf-8"
            ),
            headers={
                "Content-Type": "text/xml",
            },
            status_code=200,
        )


async def handle_inbound_message(
    itgs: Itgs,
    from_phone: str,
    to_phone: str,
    sms_body: str,
    is_opt_in: bool,
    is_opt_out: bool,
) -> Optional[str]:
    """Handles a verified inbound message. This doesn't guarrantee that the
    from phone number corresponds to a user or that was the number that actually
    sent the message (since SMS doesn't have a way to verify that), but it does
    verify that twilio was the one who sent us this notification

    Args:
        itgs (Itgs): the integrations to (re)use
        from_phone (str): the phone number that the sender claimed to be
        to_phone (str): the phone number that received the message
        sms_body (str): the body of the message
        is_opt_in (bool): whether the message is an opt-in message
        is_opt_out (bool): whether the message is an opt-out message

    Returns:
        (str, None): the message to reply with, if any
    """
    opted_in = is_opt_in and await try_opt_in(itgs, from_phone)
    opted_out = is_opt_out and await try_opt_out(itgs, from_phone)

    try:
        slack = await itgs.slack()
        await slack.send_oseh_bot_message(
            f"Received inbound message:\n- {is_opt_in=}, {opted_in=}\n- {is_opt_out=}, {opted_out=}\n\n{from_phone} -> {to_phone}: {sms_body}"
        )
    except:
        logger.warning("Failed to send inbound message to Slack")
        if not is_opt_in and not is_opt_out:
            return "Sorry, an error occurred. Email hi@oseh.com for support."

    if opted_out:
        return "You have successfully been unsubscribed. You will not receive any more messages from this number. Reply START to resubscribe."

    if is_opt_out:
        return "Sorry, an error occurred. Email hi@oseh.com for support."

    if opted_in:
        return "You have successfully been re-subscribed to messages from this number. Reply HELP for help. Reply STOP to unsubscribe. Msg&Data Rates May Apply."

    if is_opt_in:
        return "Sorry, an error occurred. Email hi@oseh.com for support."

    return "Your message has been received. Reply STOP to stop, HELP for help."


async def try_opt_in(itgs: Itgs, phone: str) -> bool:
    """Attempts to opt the given phone number into daily sms notifications. This
    can only do so if we have an unambiguous user to opt in. If we find that user
    we verify their phone number.
    """
    conn = await itgs.conn()
    cursor = conn.cursor()

    response = await cursor.execute(
        """
        SELECT
            users.sub,
            users.email,
            users.phone_number_verified,
            EXISTS (
                SELECT 1 FROM user_daily_reminders
                WHERE 
                    user_daily_reminders.user_id = users.id
                    AND user_daily_reminders.channel = 'sms'
            ) AS b1
        FROM users
        WHERE
            users.phone_number = ?
        LIMIT 2
        """,
        (phone,),
    )

    if not response.results:
        return False

    if len(response.results) > 1:
        return False

    user_sub: str = response.results[0][0]
    user_email: str = response.results[0][1]
    user_phone_number_verified: bool = bool(response.results[0][2])
    user_has_daily_reminder: bool = bool(response.results[0][3])

    if user_phone_number_verified and user_has_daily_reminder:
        return False

    daily_reminder_uid = f"oseh_udr_{secrets.token_urlsafe(16)}"
    now = time.time()
    response = await cursor.executemany3(
        (
            (
                "UPDATE users SET phone_number_verified = 1 WHERE sub = ? AND phone_number = ?",
                (user_sub, phone),
            ),
            (
                """
                INSERT INTO user_daily_reminders (
                    uid, user_id, channel, start_time, end_time, day_of_week_mask, created_at
                )
                SELECT
                    ?, users.id, 'sms', 32400, 39600, 127, ?
                FROM users
                WHERE users.sub = ? AND users.phone_number = ?
                """,
                (daily_reminder_uid, now, user_sub, phone),
            ),
        )
    )

    if response[0].rows_affected != 1 and response[1].rows_affected != 1:
        return False

    if response[1].rows_affected > 0:
        stats = DailyReminderRegistrationStatsPreparer()
        stats.incr_subscribed(
            unix_dates.unix_timestamp_to_unix_date(
                now, tz=pytz.timezone("America/Los_Angeles")
            ),
            "sms",
            "sms_start",
        )
        await stats.store(itgs)

    try:
        base_url = os.environ["ROOT_FRONTEND_URL"]
        user_url = f"{base_url}/admin/user?sub={user_sub}"

        slack = await itgs.slack()
        await slack.send_oseh_bot_message(
            f"{user_email} ({phone}) opted into daily SMS reminders via START message. <view user|{user_url}>",
            preview=f"{phone} sent START",
        )
    except:
        logger.exception("Failed to send START message to Slack")

    return True


async def try_opt_out(itgs: Itgs, phone: str) -> bool:
    """Attempts to opt the given phone number out of daily sms notifications. This
    only works if we can find a user with the given phone number which is
    receiving notifications
    """
    conn = await itgs.conn()
    cursor = conn.cursor()

    response = await cursor.execute(
        """
        SELECT
            users.sub,
            users.email
        FROM users
        WHERE
            users.phone_number = ?
            AND users.phone_number_verified = 1
            AND EXISTS (
                SELECT 1 FROM user_daily_reminders
                WHERE 
                    user_daily_reminders.user_id = users.id
                    AND user_daily_reminders.channel = 'sms'
            )
        ORDER by users.sub ASC
        """,
        (phone,),
    )

    users: List[Tuple[str, str, str]] = response.results or []

    if not users:
        return False

    now = time.time()
    response = await cursor.execute(
        """
        DELETE FROM user_daily_reminders
        WHERE
            EXISTS (
                SELECT 1 FROM users
                WHERE users.id = user_daily_reminders.user_id
                  AND users.phone_number = ?
                  AND users.phone_number_verified = 1
            )
            AND user_daily_reminders.channel = 'sms'
        """,
        (phone,),
    )

    if response.rows_affected is None or response.rows_affected == 0:
        return False

    subscriptions_removed = response.rows_affected
    stats = DailyReminderRegistrationStatsPreparer()
    stats.incr_unsubscribed(
        unix_dates.unix_timestamp_to_unix_date(
            now, tz=pytz.timezone("America/Los_Angeles")
        ),
        "sms",
        "sms_stop",
        amt=subscriptions_removed,
    )
    await stats.store(itgs)

    try:
        base_url = os.environ["ROOT_FRONTEND_URL"]
        user_urls = [f"{base_url}/admin/user?sub={user_sub}" for user_sub, _ in users]

        users_list = "\n".join(
            f"- <{user_url}|{user_email}>"
            for (_, user_email), user_url in zip(users, user_urls)
        )

        slack = await itgs.slack()
        await slack.send_oseh_bot_message(
            f"{phone} sent STOP message, removed {subscriptions_removed} subscriptions. users:\n{users_list}",
            preview=f"{phone} sent STOP",
        )
    except:
        logger.exception("Failed to send STOP message to Slack")

    return True
