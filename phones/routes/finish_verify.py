import json
import secrets
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal, Optional
from error_middleware import handle_error, handle_warning
from lib.contact_methods.contact_method_stats import contact_method_stats
from lib.daily_reminders.registration_stats import (
    DailyReminderRegistrationStatsPreparer,
)
from lib.shared.clean_for_slack import clean_for_slack
from lib.shared.describe_user import enqueue_send_described_user_slack_message
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from starlette.concurrency import run_in_threadpool
from twilio.base.exceptions import TwilioRestException
from auth import auth_id
from itgs import Itgs
from loguru import logger
from dataclasses import dataclass
import users.lib.stats
import unix_dates
import pytz
import socket
import time
import os


class FinishVerifyRequest(BaseModel):
    uid: str = Field(description="The UID of the phone verification to finish")
    code: str = Field(
        description="The code that was sent to the phone number",
        min_length=1,
        max_length=60,
    )


class FinishVerifyResponse(BaseModel):
    verified_at: float = Field(
        description="The timestamp at which the verification was completed, in seconds since the unix epoch"
    )


ERROR_404_TYPES = Literal["phone_verification_not_found"]
ERROR_429_TYPES = Literal["too_many_verification_attempts"]


router = APIRouter()


@router.post(
    "/verify/finish",
    status_code=201,
    response_model=FinishVerifyResponse,
    responses={
        "404": {
            "description": "That phone verification does not exist, has a different code, or is already completed",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        "429": {
            "description": "Too many verification attempts have been made",
            "model": StandardErrorResponse[ERROR_429_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def finish_verify(
    args: FinishVerifyRequest, authorization: Optional[str] = Header(None)
):
    """Finishes a phone verification by checking the code that was sent to the phone number.

    This requires id token verification via the standard authorization header.
    """
    async with Itgs() as itgs:
        auth_result = await auth_id(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        redis = await itgs.redis()
        key = f"phone_verifications:{auth_result.result.sub}:finish"
        async with redis.pipeline() as pipe:
            pipe.multi()
            await pipe.incr(key)
            await pipe.expire(key, 600)
            response = await pipe.execute()

        if response[0] > 5:
            return Response(
                status_code=429,
                content=StandardErrorResponse[ERROR_429_TYPES](
                    type="too_many_verification_attempts",
                    message="Too many verification attempts have been made recently",
                ).json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        conn = await itgs.conn()
        cursor = conn.cursor("weak")

        response = await cursor.execute(
            """
            SELECT phone_number, enabled
            FROM phone_verifications
            WHERE
                uid = ?
                AND status = ?
                AND EXISTS (
                    SELECT 1 FROM users
                    WHERE users.id = phone_verifications.user_id
                      AND users.sub = ?
                )
                AND started_at > ?
            """,
            (args.uid, "pending", auth_result.result.sub, time.time() - 60 * 10),
        )

        if not response.results:
            return Response(
                status_code=404,
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="phone_verification_not_found",
                    message="That phone verification does not exist, has a different code, or is already completed",
                ).json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        phone_number = response.results[0][0]
        enabled = bool(response.results[0][1])
        twilio = await itgs.twilio()

        service_id = os.environ["OSEH_TWILIO_VERIFY_SERVICE_SID"]

        try:
            if os.environ["ENVIRONMENT"] == "dev" and phone_number == "+15555555555":
                response = FakeVerifyResponse(status="approved")
            else:
                response = await run_in_threadpool(
                    twilio.verify.v2.services(service_id).verification_checks.create,
                    to=phone_number,
                    code=args.code,
                )
        except TwilioRestException as e:
            if e.code != 20404:
                await handle_error(e)
            return Response(
                status_code=404,
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="phone_verification_not_found",
                    message="That phone verification does not exist, has a different code, or is already completed",
                ).json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        verified_at = (
            time.time()
            if response is not None and response.status == "approved"
            else None
        )
        new_upn_uid = f"oseh_upn_{secrets.token_urlsafe(16)}"
        insert_cml_uid = f"oseh_cml_{secrets.token_urlsafe(16)}"
        verify_cml_uid = f"oseh_cml_{secrets.token_urlsafe(16)}"
        enable_or_disable_cml_uid = f"oseh_cml_{secrets.token_urlsafe(16)}"
        new_udr_uid = f"oseh_udr_{secrets.token_urlsafe(16)}"
        cml_reason = json.dumps(
            {
                "repo": "backend",
                "file": __name__,
                "reason": "phone_verification_finished",
                "context": {
                    "phone_verification_uid": args.uid,
                },
            }
        )
        db_response = await cursor.executemany3(
            (
                (
                    "UPDATE phone_verifications SET status = ?, verified_at = ?, verification_attempts = verification_attempts + 1 WHERE uid = ?",
                    (response.status, verified_at, args.uid),
                ),
                *(
                    [
                        (
                            "INSERT INTO contact_method_log ("
                            " uid, user_id, channel, identifier, action, reason, created_at"
                            ")"
                            "SELECT"
                            " ?, users.id, 'phone', ?, 'create_verified', ?, ? "
                            "FROM users "
                            "WHERE"
                            " users.sub = ?"
                            " AND NOT EXISTS ("
                            "  SELECT 1 FROM user_phone_numbers"
                            "  WHERE"
                            "   user_phone_numbers.user_id = users.id"
                            "   AND user_phone_numbers.phone_number = ?"
                            " )",
                            (
                                insert_cml_uid,
                                phone_number,
                                cml_reason,
                                verified_at,
                                auth_result.result.sub,
                                phone_number,
                            ),
                        ),
                        (
                            "INSERT INTO contact_method_log ("
                            " uid, user_id, channel, identifier, action, reason, created_at"
                            ")"
                            "SELECT"
                            " ?, users.id, 'phone', ?, 'create_verified', ?, ? "
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
                                phone_number,
                                cml_reason,
                                verified_at,
                                auth_result.result.sub,
                                phone_number,
                            ),
                        ),
                        (
                            "INSERT INTO contact_method_log ("
                            " uid, user_id, channel, identifier, action, reason, created_at"
                            ")"
                            "SELECT"
                            " ?, users.id, 'phone', ?,"
                            " CASE WHEN user_phone_numbers.receives_notifications THEN 'disable_notifs' ELSE 'enable_notifs' END,"
                            " ?, ? "
                            "FROM users, user_phone_numbers "
                            "WHERE"
                            " user_phone_numbers.user_id = users.id"
                            " AND user_phone_numbers.phone_number = ?"
                            " AND users.sub = ?"
                            " AND user_phone_numbers.receives_notifications <> ?",
                            (
                                enable_or_disable_cml_uid,
                                phone_number,
                                cml_reason,
                                verified_at,
                                phone_number,
                                auth_result.result.sub,
                                int(enabled),
                            ),
                        ),
                        (
                            "UPDATE user_phone_numbers "
                            "SET verified = 1, receives_notifications = ? "
                            "WHERE"
                            " EXISTS (SELECT 1 FROM users WHERE users.id = user_phone_numbers.user_id AND users.sub = ?)"
                            " AND user_phone_numbers.phone_number = ?",
                            (
                                int(enabled),
                                auth_result.result.sub,
                                phone_number,
                            ),
                        ),
                        (
                            "INSERT INTO user_phone_numbers ("
                            " uid, user_id, phone_number, verified, receives_notifications, created_at"
                            ") "
                            "SELECT ?, users.id, ?, 1, ?, ? "
                            "FROM users "
                            "WHERE"
                            " users.sub = ?"
                            " AND NOT EXISTS ("
                            "  SELECT 1 FROM user_phone_numbers AS upn "
                            "  WHERE upn.user_id = users.id AND upn.phone_number = ?"
                            " )",
                            [
                                new_upn_uid,
                                phone_number,
                                int(enabled),
                                verified_at,
                                auth_result.result.sub,
                                phone_number,
                            ],
                        ),
                        *(
                            [
                                (
                                    "DELETE FROM user_daily_reminders "
                                    "WHERE"
                                    " channel = 'sms'"
                                    " AND EXISTS ("
                                    "  SELECT 1 FROM users"
                                    "  WHERE"
                                    "   users.id = user_daily_reminders.user_id"
                                    "   AND users.sub = ?"
                                    " )"
                                    " AND NOT EXISTS ("
                                    "  SELECT 1 FROM user_phone_numbers AS upn"
                                    "  WHERE"
                                    "   upn.user_id = user_daily_reminders.user_id"
                                    "   AND upn.verified"
                                    "   AND upn.receives_notifications"
                                    "   AND upn.phone_number <> ?"
                                    "   AND NOT EXISTS ("
                                    "    SELECT 1 FROM suppressed_phone_numbers"
                                    "    WHERE"
                                    "     suppressed_phone_numbers.phone_number = upn.phone_number"
                                    "   )"
                                    " )",
                                    (
                                        auth_result.result.sub,
                                        phone_number,
                                    ),
                                )
                            ]
                            if not enabled
                            else [
                                (
                                    "INSERT INTO user_daily_reminders ("
                                    " uid, user_id, channel, start_time, end_time, day_of_week_mask, created_at"
                                    ") "
                                    "SELECT"
                                    " ?,"
                                    " users.id,"
                                    " 'sms',"
                                    " CASE"
                                    "  WHEN settings.id IS NULL THEN 28800"
                                    "  WHEN json_extract(settings.time_range, '$.type') = 'preset' THEN"
                                    "   CASE json_extract(settings.time_range, '$.preset')"
                                    "    WHEN 'afternoon' THEN 46800"
                                    "    WHEN 'evening' THEN 57600"
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
                                    "   user_daily_reminders.user_id = users.id"
                                    "   AND user_daily_reminders.channel = 'sms'"
                                    " )"
                                    " AND NOT EXISTS ("
                                    "  SELECT 1 FROM suppressed_phone_numbers"
                                    "  WHERE"
                                    "   suppressed_phone_numbers.phone_number = ?"
                                    " )"
                                    " AND (settings.day_of_week_mask IS NULL OR settings.day_of_week_mask <> 0)",
                                    (
                                        new_udr_uid,
                                        verified_at,
                                        auth_result.result.sub,
                                        phone_number,
                                    ),
                                )
                            ]
                        ),
                    ]
                    if verified_at is not None
                    else []
                ),
            )
        )

        if verified_at is None:
            return Response(
                status_code=404,
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="phone_verification_not_found",
                    message="That phone verification does not exist, has a different code, or is already completed",
                ).json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        def debug_info():
            return f"\n\n```\n{clean_for_slack(repr(db_response))}\n```"

        affected = [
            r.rows_affected is not None and r.rows_affected > 0 for r in db_response
        ]
        if any(a and r.rows_affected != 1 for (a, r) in zip(affected, db_response)):
            await handle_warning(
                f"{__name__}:multiple_rows_affected",
                "Strange result from verifying phone number; expected at most one row affected "
                f"per query, but got:{debug_info()}",
            )

        (
            _,
            create_logged,
            verify_logged,
            enable_or_disable_logged,
            phone_updated,
            phone_inserted,
            *rest,
        ) = affected
        if enabled:
            udr_created = rest[0]
            udr_deleted = None
            rest = rest[1:]
        else:
            udr_created = None
            udr_deleted = rest[0]
            rest = rest[1:]
        assert not rest, rest

        if create_logged and (
            verify_logged or enable_or_disable_logged or phone_updated
        ):
            await handle_warning(
                f"{__name__}:create_and_mutate_logged",
                f"Both created and mutated a phone?{debug_info()}",
            )

        if not create_logged and not phone_updated:
            await handle_warning(
                f"{__name__}:no_create_or_update",
                f"Did not log inserting a row but also did not update a row:{debug_info()}",
            )

        if create_logged and not phone_inserted:
            await handle_warning(
                f"{__name__}:create_logged_but_no_insert",
                f"Logged creating a row but did not insert a row:{debug_info()}",
            )

        if phone_updated and phone_inserted:
            await handle_warning(
                f"{__name__}:phone_updated_and_inserted",
                f"Updated a phone number and inserted a phone number:{debug_info()}",
            )

        unix_date = unix_dates.unix_timestamp_to_unix_date(
            verified_at, tz=pytz.timezone("America/Los_Angeles")
        )
        async with contact_method_stats(itgs) as stats:
            if create_logged:
                logger.info(
                    f"Phone number {phone_number} attached to {auth_result.result.sub}"
                )
                stats.incr_created(
                    unix_date,
                    channel="phone",
                    verified=True,
                    enabled=enabled,
                    reason="verify",
                )
            if verify_logged:
                logger.info(
                    f"Phone number {phone_number} verified for {auth_result.result.sub}"
                )
                stats.incr_verified(unix_date, channel="phone", reason="verify")
            if enable_or_disable_logged and enabled:
                logger.info(
                    f"Phone number {phone_number} enabled for {auth_result.result.sub}"
                )
                stats.incr_enabled(unix_date, channel="phone", reason="verify")
            if enable_or_disable_logged and not enabled:
                logger.info(
                    f"Phone number {phone_number} disabled for {auth_result.result.sub}"
                )
                stats.incr_disabled(unix_date, channel="phone", reason="verify")
            if udr_created:
                logger.info(
                    f"User {auth_result.result.sub} registered for reminders via sms"
                )
                stats.stats.merge_with(
                    DailyReminderRegistrationStatsPreparer().incr_subscribed(
                        unix_date, channel="sms", reason="phone_verify_finish"
                    )
                )
            if udr_deleted:
                logger.info(
                    f"User {auth_result.result.sub} unregistered for reminders via sms"
                )
                stats.stats.merge_with(
                    DailyReminderRegistrationStatsPreparer().incr_unsubscribed(
                        unix_date, channel="sms", reason="unreachable"
                    )
                )

        debug_hint = "".join(
            "1"
            if len(affected) > i and affected[i]
            else "0"
            if len(affected) > i and not affected[i]
            else "x"
            for i in range(7)
        )

        if os.environ["ENVIRONMENT"] != "dev":
            await enqueue_send_described_user_slack_message(
                itgs,
                message=f"{{name}} just verified their phone number: {phone_number}\n •  Debug Hint: `{debug_hint}`",
                sub=auth_result.result.sub,
                channel="oseh_bot",
            )

        return Response(
            status_code=201,
            content=FinishVerifyResponse(verified_at=verified_at).json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )


@dataclass
class FakeVerifyResponse:
    status: str
