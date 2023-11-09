import io
import json
from typing import List, Optional, Tuple
from fastapi import APIRouter
from fastapi.requests import Request
from fastapi.responses import Response
import hmac
from error_middleware import handle_error, handle_warning
from itgs import Itgs
import time
import os
import urllib.parse
import base64
from starlette.datastructures import URL
from loguru import logger
import secrets
from lib.contact_methods.contact_method_stats import contact_method_stats
from lib.shared.clean_for_slack import clean_for_slack
from lib.shared.describe_user import enqueue_send_described_user_slack_message
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
            users.sub
        FROM users
        WHERE
            EXISTS (
                SELECT 1 FROM user_phone_numbers
                WHERE 
                    user_phone_numbers.user_id = users.id
                    AND user_phone_numbers.phone_number = ?
            )
        LIMIT 2
        """,
        (phone,),
    )

    if not response.results:
        await handle_warning(
            f"{__name__}:unknown_phone_number",
            f"Could not opt in {phone} because it is not associated with any user",
        )
        return False

    if len(response.results) > 1:
        await handle_warning(
            f"{__name__}:ambiguous_phone_number",
            f"Could not opt in {phone} because it is associated with multiple users",
        )
        return False

    user_sub: str = response.results[0][0]

    verify_cml_uid = f"oseh_cml_{secrets.token_urlsafe(16)}"
    enable_cml_uid = f"oseh_cml_{secrets.token_urlsafe(16)}"
    cml_reason = json.dumps({"repo": "backend", "file": __name__, "reason": "START"})
    daily_reminder_uid = f"oseh_udr_{secrets.token_urlsafe(16)}"
    now = time.time()
    unix_date = unix_dates.unix_timestamp_to_unix_date(
        now, tz=pytz.timezone("America/Los_Angeles")
    )
    response = await cursor.executemany3(
        (
            (
                "INSERT INTO contact_method_log ("
                " uid, user_id, channel, identifier, action, reason, created_at"
                ") "
                "SELECT"
                " ?, users.id, 'phone', ?, 'verify', ?, ? "
                "FROM users "
                "WHERE"
                " users.sub = ?"
                " AND EXISTS ("
                "  SELECT 1 FROM user_phone_numbers"
                "  WHERE"
                "   user_phone_numbers.user_id = users.id"
                "   AND user_phone_numbers.phone_number = ?"
                "   AND NOT user_phone_numbers.verified"
                " )",
                (
                    verify_cml_uid,
                    phone,
                    cml_reason,
                    now,
                    user_sub,
                    phone,
                ),
            ),
            (
                "INSERT INTO contact_method_log ("
                " uid, user_id, channel, identifier, action, reason, created_at"
                ") "
                "SELECT"
                " ?, users.id, 'phone', ?, 'enable_notifs', ?, ? "
                "FROM users "
                "WHERE"
                " users.sub = ?"
                " AND EXISTS ("
                "  SELECT 1 FROM user_phone_numbers"
                "  WHERE"
                "   user_phone_numbers.user_id = users.id"
                "   AND user_phone_numbers.phone_number = ?"
                "   AND NOT user_phone_numbers.receives_notifications"
                " )",
                (
                    enable_cml_uid,
                    phone,
                    cml_reason,
                    now,
                    user_sub,
                    phone,
                ),
            ),
            (
                "UPDATE user_phone_numbers "
                "SET verified = 1, receives_notifications = 1 "
                "WHERE"
                " EXISTS ("
                "  SELECT 1 FROM users"
                "  WHERE"
                "   users.id = user_phone_numbers.user_id"
                "   AND users.sub = ?"
                " )"
                " AND user_phone_numbers.phone_number = ?",
                (
                    user_sub,
                    phone,
                ),
            ),
            (
                "INSERT INTO user_daily_reminders ("
                " uid, user_id, channel, start_time, end_time, day_of_week_mask, created_at"
                ") "
                "SELECT"
                " ?,"
                " users.id,"
                " 'sms',"
                " CASE"
                "  WHEN settings.id IS NULL THEN 21600"
                "  WHEN json_extract(settings.time_range, '$.type') = 'preset' THEN"
                "   CASE json_extract(settings.time_range, '$.preset')"
                "    WHEN 'afternoon' THEN 46800"
                "    WHEN 'evening' THEN 61200"
                "    ELSE 28800"
                "   END"
                "  WHEN json_extract(settings.time_range, '$.type') = 'explicit' THEN"
                "   json_extract(settings.time_range, '$.start')"
                "  ELSE 28800"
                " END,"
                " CASE"
                "  WHEN settings.id IS NULL THEN 39600"
                "  WHEN json_extract(settings.time_range, '$.type') = 'preset' THEN"
                "   CASE json_extract(settings.time_range, '$.preset')"
                "    WHEN 'afternoon' THEN 57600"
                "    WHEN 'evening' THEN 61200"
                "    ELSE 39600"
                "   END"
                "  WHEN json_extract(settings.time_range, '$.type') = 'explicit' THEN"
                "   json_extract(settings.time_range, '$.end')"
                "  ELSE 39600"
                " END,"
                " COALESCE(settings.day_of_week_mask, 127),"
                " ? "
                "FROM users "
                "LEFT OUTER JOIN user_daily_reminder_settings AS settings "
                "ON settings.id = ("
                " SELECT s.id FROM user_daily_reminder_settings AS s"
                " WHERE"
                "  s.user_id = users.id"
                "  AND (s.channel = 'sms' OR s.day_of_week_mask <> 0)"
                " ORDER BY"
                "  s.channel = 'sms' DESC,"
                "  CASE json_extract(s.time_range, '$.type')"
                "   WHEN 'explicit' THEN 0"
                "   WHEN 'preset' THEN 1"
                "   ELSE 2"
                "  END ASC,"
                "  (s.day_of_week_mask & 1 > 0) + (s.day_of_week_mask & 2 > 0) + (s.day_of_week_mask & 4 > 0) + (s.day_of_week_mask & 8 > 0) + (s.day_of_week_mask & 16 > 0) + (s.day_of_week_mask & 32 > 0) + (s.day_of_week_mask & 64 > 0) ASC,"
                "  CASE s.channel"
                "   WHEN 'sms' THEN 0"
                "   WHEN 'push' THEN 1"
                "   WHEN 'email' THEN 2"
                "   ELSE 3"
                "  END ASC"
                "  LIMIT 1"
                ") "
                "WHERE"
                " users.sub = ?"
                " AND NOT EXISTS ("
                "  SELECT 1 FROM user_daily_reminders"
                "  WHERE"
                "   user_daily_reminders.user_id = users.sub"
                "   AND user_daily_reminders.channel = 'sms'"
                " )"
                " AND EXISTS ("
                "  SELECT 1 FROM user_phone_numbers"
                "  WHERE user_phone_numbers.user_id = users.id"
                "   AND user_phone_numbers.phone_number = ?"
                " )"
                " AND (settings.day_of_week_mask IS NULL OR settings.day_of_week_mask <> 0)",
                (
                    daily_reminder_uid,
                    now,
                    user_sub,
                    phone,
                ),
            ),
            ("DELETE FROM suppressed_phone_numbers WHERE phone_number = ?", (phone,)),
        )
    )

    def debug_info():
        return f"\n\n```\n{clean_for_slack(repr(response))}\n```\n"

    affected = [r.rows_affected is not None and r.rows_affected > 0 for r in response]
    if any(a and r.rows_affected != 1 for (a, r) in zip(affected, response)):
        await handle_warning(
            f"{__name__}:multiple_rows_affected",
            f"Expected at most 1 row affected per query{debug_info()}",
        )

    (
        verify_logged,
        enable_logged,
        phone_updated,
        daily_reminder_created,
        suppression_removed,
    ) = affected

    if not phone_updated and daily_reminder_created:
        await handle_warning(
            f"{__name__}:daily_reminder_created_without_phone_updated",
            f"Expected phone number to be updated when daily reminder created{debug_info()}",
        )

    async with contact_method_stats(itgs) as stats:
        if verify_logged:
            logger.info(f"Verified {phone} via SMS start")
            await stats.incr_verified(unix_date, channel="phone", reason="sms_start")
        if enable_logged:
            logger.info(f"Enabled {phone} via SMS start")
            await stats.incr_enabled(unix_date, channel="phone", reason="sms_start")
        if daily_reminder_created:
            logger.info(f"Created daily reminder for {phone} via SMS start")
            stats.stats.merge_with(
                DailyReminderRegistrationStatsPreparer().incr_subscribed(
                    unix_date, "sms", "sms_start"
                )
            )

    if suppression_removed:
        logger.info(f"Removed suppression on phone {phone} via SMS start")

    if verify_logged or enable_logged or daily_reminder_created or suppression_removed:
        await enqueue_send_described_user_slack_message(
            itgs,
            message=f"{{name}} opted into daily SMS reminders via START message from {phone}",
            sub=user_sub,
            channel="oseh_bot",
        )

        return True

    return False


async def try_opt_out(itgs: Itgs, phone: str) -> bool:
    """Suppresses the given phone number, if it's not already suppressed"""
    conn = await itgs.conn()
    cursor = conn.cursor()

    new_spn_uid = f"oseh_spn_{secrets.token_urlsafe(16)}"
    now = time.time()
    unix_date = unix_dates.unix_timestamp_to_unix_date(
        now, tz=pytz.timezone("America/Los_Angeles")
    )
    response = await cursor.executemany3(
        (
            (
                """
            INSERT INTO suppressed_phone_numbers (
                uid, phone_number, reason, reason_details, created_at
            )
            SELECT
                ?, ?, 'Stop', '{}', ?
            WHERE
                NOT EXISTS (
                    SELECT 1 FROM suppressed_phone_numbers AS spn
                    WHERE spn.phone_number = ?
                )
            """,
                (
                    new_spn_uid,
                    phone,
                    now,
                    phone,
                ),
            ),
            (
                """
            DELETE FROM user_daily_reminders
            WHERE
                user_daily_reminders.channel = 'sms'
                AND EXISTS (
                    SELECT 1 FROM user_phone_numbers
                    WHERE
                        user_phone_numbers.user_id = user_daily_reminders.user_id
                        AND user_phone_numbers.phone_number = ?
                )
                AND NOT EXISTS (
                    SELECT 1 FROM user_phone_numbers
                    WHERE
                        user_phone_numbers.user_id = user_daily_reminders.user_id
                        AND user_phone_numbers.phone_number <> ?
                        AND user_phone_numbers.verified
                        AND user_phone_numbers.receives_notifications
                        AND NOT EXISTS (
                            SELECT 1 FROM suppressed_phone_numbers
                            WHERE
                                suppressed_phone_numbers.phone_number = user_phone_numbers.phone_number
                        )
                )
            """,
                (
                    phone,
                    phone,
                ),
            ),
        )
    )

    affected = [r.rows_affected is not None and r.rows_affected > 0 for r in response]
    suppressed, deleted = affected
    if suppressed and response[0].rows_affected != 1:
        await handle_warning(
            f"{__name__}:try_opt_out:multiple_rows_affected",
            f"Expected at most 1 suppressed phone number, got\n\n```\n{response=}\n```",
        )

    if not suppressed and deleted:
        await handle_warning(
            f"{__name__}:try_opt_out:deleted_without_suppressed",
            f"Expected suppressed phone number to be created when deleting reminders, got\n\n```\n{response=}\n```",
        )

    if deleted:
        await (
            DailyReminderRegistrationStatsPreparer()
            .incr_unsubscribed(
                unix_date, "sms", "sms_stop", amt=response[1].rows_affected
            )
            .store(itgs)
        )

    if suppressed:
        try:
            slack = await itgs.slack()
            await slack.send_oseh_bot_message(
                f"{phone} sent STOP message, suppressed and deleted {response[1].rows_affected or 0} daily reminder registrations",
                preview=f"{phone} sent STOP",
            )
        except:
            logger.exception("Failed to send STOP message to Slack")

    return True
