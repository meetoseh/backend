"""Contains the merging queries"""

import json
import secrets
import traceback
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    Literal,
    Optional,
    Sequence,
    Tuple,
    cast,
)
from pydantic import BaseModel, Field
from admin.logs.routes.read_daily_reminder_settings_log import (
    create_day_of_week_mask,
    interpret_day_of_week_mask,
)
from error_middleware import handle_error
from file_service import AsyncWritableBytesIO
from itgs import Itgs
from lib.daily_reminders.registration_stats import (
    Channel,
    DailyReminderRegistrationStatsPreparer,
)
from lib.daily_reminders.setting_stats import DailyReminderTimeRange
from oauth.lib.merging.operation_order import OperationOrder
from oauth.lib.merging.query import MergeContext, MergeQuery
from dataclasses import dataclass
from rqdb.result import ResultItem
from rqdb.async_cursor import AsyncCursor
from functools import partial
import unix_dates
import pytz
from users.me.routes.read_daily_reminder_settings import (
    EMAIL_PREFERRED_CHANNELS,
    PUSH_PREFERRED_CHANNELS,
    SMS_PREFERRED_CHANNELS,
    DailyReminderChannelSettings,
    ReadDailyReminderSettingsResponse,
    RealDailyReminderChannelSettings,
    get_implied_settings,
)

from visitors.routes.associate_visitor_with_user import QueuedVisitorUser


@dataclass
class _Ctx:
    confirm_log_uid: str
    confirm_required_step_result: str
    operation_uid: str
    original_user_sub: str
    merging_provider: Literal["Direct", "Google", "SignInWithApple"]
    merging_provider_sub: str
    email_hint: Optional[str]
    phone_hint: Optional[str]
    log: AsyncWritableBytesIO
    merge_at: float


async def create_merging_queries(
    itgs: Itgs,
    *,
    confirm_log_uid: str,
    confirm_required_step_result: str,
    operation_uid: str,
    original_user_sub: str,
    merging_provider: Literal["Direct", "Google", "SignInWithApple"],
    merging_provider_sub: str,
    email_hint: Optional[str],
    phone_hint: Optional[str],
    log: AsyncWritableBytesIO,
    merge_at: float,
) -> Sequence[MergeQuery]:
    """Constructs all the queries required"""
    ctx = _Ctx(
        confirm_log_uid=confirm_log_uid,
        confirm_required_step_result=confirm_required_step_result,
        operation_uid=operation_uid,
        original_user_sub=original_user_sub,
        merging_provider=merging_provider,
        merging_provider_sub=merging_provider_sub,
        email_hint=email_hint,
        phone_hint=phone_hint,
        log=log,
        merge_at=merge_at,
    )

    return [
        *await _create_standard_move_merge_queries(
            itgs,
            ctx,
            table_name="emotion_users",
            operation_order=OperationOrder.move_emotion_users,
        ),
        *await _create_standard_move_merge_queries(
            itgs,
            ctx,
            table_name="inapp_notification_users",
            operation_order=OperationOrder.move_inapp_notification_users,
        ),
        *await _create_standard_move_merge_queries(
            itgs,
            ctx,
            table_name="instructor_profile_pictures",
            operation_order=OperationOrder.move_instructor_profile_pictures,
            column_name="uploaded_by_user_id",
        ),
        *await _create_standard_move_merge_queries(
            itgs,
            ctx,
            table_name="interactive_prompt_sessions",
            operation_order=OperationOrder.move_interactive_prompt_sessions,
        ),
        *await _create_standard_move_merge_queries(
            itgs,
            ctx,
            table_name="introductory_journeys",
            operation_order=OperationOrder.move_introductory_journeys,
        ),
        *await _create_standard_move_merge_queries(
            itgs,
            ctx,
            table_name="journey_audio_contents",
            operation_order=OperationOrder.move_journey_audio_contents,
            column_name="uploaded_by_user_id",
        ),
        *await _create_standard_move_merge_queries(
            itgs,
            ctx,
            table_name="journey_background_images",
            operation_order=OperationOrder.move_journey_background_images,
            column_name="uploaded_by_user_id",
        ),
        *await _create_standard_move_merge_queries(
            itgs,
            ctx,
            table_name="journey_feedback",
            operation_order=OperationOrder.move_journey_feedback,
        ),
        *await _create_standard_move_merge_queries(
            itgs,
            ctx,
            table_name="journey_public_link_views",
            operation_order=OperationOrder.move_journey_public_link_views,
        ),
        *await _create_standard_move_merge_queries(
            itgs,
            ctx,
            table_name="open_stripe_checkout_sessions",
            operation_order=OperationOrder.move_open_stripe_checkout_sessions,
        ),
        *await _create_standard_move_merge_queries(
            itgs,
            ctx,
            table_name="phone_verifications",
            operation_order=OperationOrder.move_phone_verifications,
        ),
        *await _create_standard_move_merge_queries(
            itgs,
            ctx,
            table_name="stripe_customers",
            operation_order=OperationOrder.move_stripe_customers,
            reason_extra=", '$.context.ids', (SELECT json_group_array(stripe_customer_id) FROM stripe_customers WHERE stripe_customers.user_id = merging_user.id)",
        ),
        *await _move_user_email_addresses__disable_without_hint(
            itgs, ctx
        ),  # MUST be before user daily reminders deleted
        *await _move_user_email_addresses__transfer(itgs, ctx),
        *await _move_user_email_addresses__verify(itgs, ctx),
        *await _move_user_email_addresses__disable(itgs, ctx),
        *await _create_standard_move_merge_queries(
            itgs,
            ctx,
            table_name="user_identities",
            operation_order=OperationOrder.move_user_identities,
            reason_extra=", '$.context.merging', (SELECT json_group_array(json_object('uid', ui.uid, 'provider', ui.provider, 'sub', ui.sub)) FROM user_identities AS ui WHERE ui.user_id = merging_user.id)",
        ),
        *await _create_standard_move_merge_queries(
            itgs,
            ctx,
            table_name="user_journeys",
            operation_order=OperationOrder.move_user_journeys,
        ),
        *await _move_user_likes(itgs, ctx),
        *await _move_user_phone_numbers__disable_without_hint(
            itgs, ctx
        ),  # MUST be before user daily reminders deleted
        *await _move_user_phone_numbers__transfer(itgs, ctx),
        *await _move_user_phone_numbers__verify(itgs, ctx),
        *await _move_user_phone_numbers__disable(itgs, ctx),
        *await _move_user_profile_pictures(itgs, ctx),
        *await _create_standard_move_merge_queries(
            itgs,
            ctx,
            table_name="user_push_tokens",
            operation_order=OperationOrder.move_user_push_tokens,
        ),
        *await _create_standard_move_merge_queries(
            itgs,
            ctx,
            table_name="user_revenue_cat_ids",
            operation_order=OperationOrder.move_user_revenue_cat_ids,
            reason_extra=", '$.context.merging', (SELECT json_group_array(urc.revenue_cat_id) FROM user_revenue_cat_ids AS urc WHERE urc.user_id = merging_user.id)",
        ),
        *await _create_standard_move_merge_queries(
            itgs,
            ctx,
            table_name="user_touch_link_clicks",
            operation_order=OperationOrder.move_user_touch_link_clicks,
        ),
        *await _create_standard_move_merge_queries(
            itgs,
            ctx,
            table_name="user_touches",
            operation_order=OperationOrder.move_user_touches,
        ),
        *await _create_standard_move_merge_queries(
            itgs,
            ctx,
            table_name="vip_chat_requests",
            column_name="user_id",
            operation_order=OperationOrder.move_vip_chat_requests__user_id,
        ),
        *await _create_standard_move_merge_queries(
            itgs,
            ctx,
            table_name="vip_chat_requests",
            column_name="added_by_user_id",
            operation_order=OperationOrder.move_vip_chat_requests__added_by_user_id,
        ),
        *await _move_visitor_users(itgs, ctx),
        *await _delete_user_daily_reminders(
            itgs, ctx
        ),  # MOVED to bottom (must be AFTER email addresses and phone numbers are moved)
        *await _create_log_move_merge_queries(
            itgs,
            ctx,
            table_name="contact_method_log",
            operation_order=OperationOrder.move_contact_method_log,
        ),
        *await _create_log_move_merge_queries(
            itgs,
            ctx,
            table_name="daily_reminder_settings_log",
            operation_order=OperationOrder.move_daily_reminder_settings_log,
        ),
        *await _create_log_move_merge_queries(
            itgs,
            ctx,
            table_name="merge_account_log",
            operation_order=OperationOrder.move_merge_account_log,
        ),
        *await _create_standard_move_merge_queries(
            itgs,
            ctx,
            table_name="user_touch_debug_log",
            operation_order=OperationOrder.move_user_touch_debug_log,
        ),
        *await _create_move_created_at_queries(itgs, ctx),
        *await _delete_merging_user(itgs, ctx),
    ]


# Will use octx to refer to outer context and mctx to refer to merge context


async def _delete_user_daily_reminders(
    itgs: Itgs, octx: _Ctx, /
) -> Sequence[MergeQuery]:
    log_uid = f"oseh_mal_{secrets.token_urlsafe(16)}"
    await octx.log.write(
        b"- delete_user_daily_reminders -\n"
        b"computed:\n"
        b"  log_uid: " + log_uid.encode("ascii") + b"\n"
    )

    logged: Optional[bool] = None
    logged_rows: Optional[int] = None

    async def update_reminders_to_reflect_settings(mctx: MergeContext) -> None:
        await mctx.log.write(
            b"- update reminders to reflect settings -\n"
            b"going to fetch the user's daily reminder settings\n"
            b"and their actual user daily reminder records, and make any\n"
            b"necessary changes so that they are consistent\n"
        )

        conn = await itgs.conn()
        cursor = conn.cursor("weak")
        response = await _log_and_execute_query(
            cursor,
            (
                "SELECT"
                " udrs.channel, udrs.day_of_week_mask, udrs.time_range "
                "FROM user_daily_reminder_settings AS udrs, users "
                "WHERE udrs.user_id = users.id AND users.sub = ?"
            ),
            (octx.original_user_sub,),
            mctx.log,
        )

        settings_by_channel: Dict[str, RealDailyReminderChannelSettings] = dict()

        for row_channel, row_day_of_week_mask, row_time_range in response.results or []:
            settings_by_channel[row_channel] = RealDailyReminderChannelSettings(
                channel=row_channel,
                days=interpret_day_of_week_mask(row_day_of_week_mask),
                time_range=DailyReminderTimeRange.parse_db(row_time_range),
            )

        await mctx.log.write(
            b"got the user's daily reminder settings:\n"
            + RealDailyReminderChannelSettings.__pydantic_serializer__.to_json(
                settings_by_channel, indent=2
            )
            + b"\n"
        )

        implied_settings = ReadDailyReminderSettingsResponse(
            email=get_implied_settings(
                settings_by_channel, "email", EMAIL_PREFERRED_CHANNELS
            ),
            sms=get_implied_settings(
                settings_by_channel, "sms", SMS_PREFERRED_CHANNELS
            ),
            push=get_implied_settings(
                settings_by_channel, "push", PUSH_PREFERRED_CHANNELS
            ),
        )

        await mctx.log.write(
            b"implied settings:\n"
            + implied_settings.__pydantic_serializer__.to_json(
                implied_settings, indent=2
            )
            + b"\n\ngoing to fetch if the user actually can receive reminders on these channels\n"
        )

        can_receive_on_channel: Dict[Channel, bool] = dict()

        if implied_settings.email.days:
            response = await _log_and_execute_query(
                cursor,
                "SELECT 1 FROM user_email_addresses "
                "WHERE"
                " EXISTS ("
                "  SELECT 1 FROM users"
                "  WHERE users.id = user_email_addresses.user_id"
                "  AND users.sub = ?"
                " )"
                " AND user_email_addresses.verified"
                " AND user_email_addresses.receives_notifications"
                " AND NOT EXISTS ("
                "  SELECT 1 FROM suppressed_emails"
                "  WHERE suppressed_emails.email_address = user_email_addresses.email COLLATE NOCASE"
                " ) "
                "LIMIT 1",
                (octx.original_user_sub,),
                mctx.log,
            )
            can_receive_on_channel["email"] = bool(response.results)

        if implied_settings.sms.days:
            response = await _log_and_execute_query(
                cursor,
                "SELECT 1 FROM user_phone_numbers "
                "WHERE"
                " EXISTS ("
                "  SELECT 1 FROM users"
                "  WHERE users.id = user_phone_numbers.user_id"
                "  AND users.sub = ?"
                " )"
                " AND user_phone_numbers.verified"
                " AND user_phone_numbers.receives_notifications"
                " AND NOT EXISTS ("
                "  SELECT 1 FROM suppressed_phone_numbers"
                "  WHERE suppressed_phone_numbers.phone_number = user_phone_numbers.phone_number"
                " ) "
                "LIMIT 1",
                (octx.original_user_sub,),
                mctx.log,
            )
            can_receive_on_channel["sms"] = bool(response.results)

        if implied_settings.push.days:
            response = await _log_and_execute_query(
                cursor,
                "SELECT 1 FROM user_push_tokens "
                "WHERE"
                " EXISTS ("
                "  SELECT 1 FROM users"
                "  WHERE users.id = user_push_tokens.user_id"
                "  AND users.sub = ?"
                " )"
                " AND user_push_tokens.receives_notifications",
                (octx.original_user_sub,),
                mctx.log,
            )
            can_receive_on_channel["push"] = bool(response.results)

        await mctx.log.write(
            b"can_receive_on_channel=\n"
            + json.dumps(can_receive_on_channel, indent=2).encode("utf-8")
            + b"\n\ngoing to fetch the user's actual daily reminder records\n"
        )
        response = await _log_and_execute_query(
            cursor,
            (
                "SELECT"
                " udr.channel, udr.start_time, udr.end_time, udr.day_of_week_mask "
                "FROM user_daily_reminders AS udr, users "
                "WHERE udr.user_id = users.id AND users.sub = ?"
            ),
            (octx.original_user_sub,),
            mctx.log,
        )

        registrations_by_channel: Dict[
            str, Optional[DailyReminderChannelSettings]
        ] = dict()
        for (
            row_channel,
            row_start_time,
            row_end_time,
            row_day_of_week_mask,
        ) in (
            response.results or []
        ):
            registrations_by_channel[row_channel] = DailyReminderChannelSettings(
                start=row_start_time,
                end=row_end_time,
                days=interpret_day_of_week_mask(row_day_of_week_mask),
                is_real=False,
            )

        await mctx.log.write(
            b"got the user's actual daily reminder records:\n"
            + DailyReminderChannelSettings.__pydantic_serializer__.to_json(
                registrations_by_channel, indent=2
            )
            + b"\n"
        )

        reg_stats = DailyReminderRegistrationStatsPreparer()
        unix_date = unix_dates.unix_timestamp_to_unix_date(
            octx.merge_at, tz=pytz.timezone("America/Los_Angeles")
        )
        for channel in ("sms", "email", "push"):
            expected = cast(
                DailyReminderChannelSettings, getattr(implied_settings, channel)
            )
            actual = registrations_by_channel.get(channel)

            if not can_receive_on_channel.get(channel):
                expected = DailyReminderChannelSettings(
                    start=expected.start, end=expected.end, days=[], is_real=False
                )

            if not expected.days and actual is not None:
                await mctx.log.write(
                    b"channel "
                    + channel.encode("ascii")
                    + b" is not expected to be registered, but is\n"
                )
                response = await _log_and_execute_query(
                    cursor,
                    "DELETE FROM user_daily_reminders "
                    "WHERE"
                    " channel=?"
                    " AND EXISTS ("
                    "  SELECT 1 FROM users"
                    "  WHERE"
                    "   users.sub = ?"
                    "   AND users.id = user_daily_reminders.user_id"
                    " )",
                    (channel, octx.original_user_sub),
                    mctx.log,
                )

                if response.rows_affected:
                    await mctx.log.write(
                        b"deleted "
                        + str(response.rows_affected).encode("ascii")
                        + b" user_daily_reminders\n"
                    )
                    reg_stats.incr_unsubscribed(unix_date, channel, "merge_consistency")
                else:
                    await mctx.log.write(
                        b"the record we wanted to delete was deleted before we got to it\n"
                    )
            elif expected.days and actual is None:
                await mctx.log.write(
                    b"channel "
                    + channel.encode("ascii")
                    + b" is expected to be registered, but is not\n"
                )
                udr_uid = f"oseh_udr_{secrets.token_urlsafe(16)}"
                await mctx.log.write(
                    b"selected udr_uid: " + udr_uid.encode("ascii") + b"\n"
                )
                response = await _log_and_execute_query(
                    cursor,
                    (
                        "INSERT INTO user_daily_reminders ("
                        " uid, user_id, channel, start_time, end_time, day_of_week_mask, created_at"
                        ") "
                        "SELECT"
                        " ?, users.id, ?, ?, ?, ?, ?"
                        "FROM users "
                        "WHERE"
                        " users.sub = ?"
                        " AND NOT EXISTS ("
                        "  SELECT 1 FROM user_daily_reminders AS udr"
                        "  WHERE"
                        "   udr.user_id = users.id"
                        "   AND udr.channel = ?"
                        " )"
                    ),
                    (
                        udr_uid,
                        channel,
                        expected.start,
                        expected.end,
                        create_day_of_week_mask(expected.days),
                        octx.merge_at,
                        octx.original_user_sub,
                        channel,
                    ),
                    mctx.log,
                )
                if response.rows_affected:
                    await mctx.log.write(
                        b"inserted "
                        + str(response.rows_affected).encode("ascii")
                        + b" user_daily_reminders\n"
                    )
                    reg_stats.incr_subscribed(unix_date, channel, "merge_consistency")
                else:
                    await mctx.log.write(
                        b"the record we wanted to insert was inserted before we got to it\n"
                    )
            elif (
                expected.days
                and actual is not None
                and (
                    sorted(expected.days) != sorted(actual.days)
                    or expected.start != actual.start
                    or expected.end != actual.end
                )
            ):
                await mctx.log.write(
                    b"channel "
                    + channel.encode("ascii")
                    + b" is registered, but with different settings\n"
                )
                response = await _log_and_execute_query(
                    cursor,
                    (
                        "UPDATE user_daily_reminders SET"
                        " start_time = ?, end_time = ?, day_of_week_mask = ?"
                        "WHERE"
                        " channel=?"
                        " AND EXISTS ("
                        "  SELECT 1 FROM users"
                        "  WHERE"
                        "   users.sub = ?"
                        "   AND users.id = user_daily_reminders.user_id"
                        " )"
                    ),
                    (
                        expected.start,
                        expected.end,
                        create_day_of_week_mask(expected.days),
                        channel,
                        octx.original_user_sub,
                    ),
                    mctx.log,
                )
                if response.rows_affected:
                    await mctx.log.write(
                        b"updated "
                        + str(response.rows_affected).encode("ascii")
                        + b" user_daily_reminders\n"
                    )
                else:
                    await mctx.log.write(
                        b"the record we wanted to update was deleted before we got to it\n"
                    )
            else:
                await mctx.log.write(
                    b"channel "
                    + channel.encode("ascii")
                    + b" matched with our computed value from their settings\n"
                )

        mctx.stats.merge_with(reg_stats)
        await mctx.log.write(b"finished updating reminders to reflect settings\n")

    async def handler(step: Literal["log", "delete"], mctx: MergeContext) -> None:
        nonlocal logged, logged_rows

        if step == "log":
            assert logged is None, "handler called twice for log step"

            if mctx.merging_expected:
                try:
                    await update_reminders_to_reflect_settings(mctx)
                except Exception as exc:
                    await handle_error(
                        exc,
                        extra_info=f"during merge `{octx.operation_uid}` into `{octx.original_user_sub}`",
                    )
                    await mctx.log.write(
                        b"while updating reminders to reflect settings:\n"
                        + traceback.format_exc().encode("utf-8")
                        + b"\n"
                    )

            logged = not not mctx.result.rows_affected

            if not logged:
                return

            await mctx.log.write(
                b"logged: true\n"
                b"interpretation: we logged that we intended to delete some user_daily_reminders "
                b"\ngoing to fetch details on what rows we should have deleted from the log entry\n"
            )

            conn = await itgs.conn()
            cursor = conn.cursor("weak")
            resp = await _log_and_execute_query(
                cursor,
                "SELECT reason FROM merge_account_log WHERE uid=?",
                (log_uid,),
                mctx.log,
            )
            assert resp.results, resp
            assert len(resp.results) == 1, resp
            assert len(resp.results[0]) == 1, resp

            parsed_reason = json.loads(resp.results[0][0])
            assert isinstance(parsed_reason, dict), resp
            await mctx.log.write(
                b"parsed_reason:\n"
                + json.dumps(parsed_reason, indent=2).encode("utf-8")
                + b"\n"
            )

            channels = parsed_reason["context"]["channels"]
            logged_rows = parsed_reason["context"]["rows"]

            assert isinstance(channels, list), resp
            assert all(isinstance(s, str) for s in channels), resp
            assert isinstance(logged_rows, int), resp
            assert len(channels) == logged_rows, resp

            await mctx.log.write(
                b"reason is correctly shaped for logged_rows="
                + str(logged_rows).encode("ascii")
                + b"\n"
                b"channels:\n" + json.dumps(channels, indent=2).encode("utf-8") + b"\n"
            )

            reg_stats = DailyReminderRegistrationStatsPreparer()
            unix_date = unix_dates.unix_timestamp_to_unix_date(
                octx.merge_at, tz=pytz.timezone("America/Los_Angeles")
            )
            for channel in channels:
                await mctx.log.write(
                    b"recording unsubscribe for channel: "
                    + cast(str, channel).encode("utf-8")
                    + b"\n"
                )
                reg_stats.incr_unsubscribed(
                    unix_date, cast(Channel, channel), "account_deleted"
                )
            await mctx.log.write(b"finished recording unsubscriptions\n")
            mctx.stats.merge_with(reg_stats)
            return

        assert step == "delete", step
        assert logged is not None, "delete step handler called before log step"
        deleted = mctx.result.rows_affected or 0
        if not logged and deleted <= 0:
            return

        assert (
            logged
        ), "deleted some user_daily_reminders, but didn't log that we intended to delete any"
        assert (
            logged_rows is not None
        ), "logged that we intended to delete some user_daily_reminders, but didn't log how many rows we intended to delete"

        await mctx.log.write(b"deleted: " + str(deleted).encode("ascii") + b"\n")

        assert (
            logged_rows == deleted
        ), f"logged that we intended to delete {logged_rows} user_daily_reminders, but deleted {deleted}"
        await mctx.log.write(b"log and delete steps matched\n")

    ctes, ctes_qargs = _merging_user_and_original_user_ctes(octx)
    return [
        MergeQuery(
            query=(
                f"{ctes}, query_ctx(channel) AS ("
                "SELECT udr.channel FROM user_daily_reminders AS udr, merging_user "
                "WHERE"
                " udr.user_id = merging_user.id"
                ") INSERT INTO merge_account_log ("
                " uid, user_id, operation_uid, operation_order, phase, step, step_result, reason, created_at"
                ") SELECT"
                " ?, original_user.id, ?, ?, 'merging', 'delete_user_daily_reminders', 'xfer',"
                " json_insert("
                "  '{}'"
                "  , '$.context.channels', (SELECT json_group_array(channel) FROM query_ctx)"
                "  , '$.context.rows', (SELECT COUNT(*) FROM query_ctx)"
                " ), ? "
                "FROM merging_user, original_user "
                "WHERE EXISTS (SELECT 1 FROM query_ctx)"
            ),
            qargs=[
                *ctes_qargs,
                log_uid,
                octx.operation_uid,
                OperationOrder.delete_user_daily_reminders.value,
                octx.merge_at,
            ],
            handler=partial(handler, "log"),
        ),
        MergeQuery(
            query=(
                f"{ctes} DELETE FROM user_daily_reminders "
                "WHERE"
                " EXISTS("
                "  SELECT 1 FROM merging_user"
                "  WHERE"
                "   merging_user.id = user_daily_reminders.user_id"
                " )"
            ),
            qargs=[*ctes_qargs],
            handler=partial(handler, "delete"),
        ),
    ]


async def _move_user_email_addresses__transfer(
    itgs: Itgs,
    octx: _Ctx,
    /,
) -> Sequence[MergeQuery]:
    log_uid = f"oseh_mal_{secrets.token_urlsafe(16)}"
    await octx.log.write(
        b"- move_user_email_addresses__transfer -\n"
        b"computed:\n"
        b"  log_uid: " + log_uid.encode("ascii") + b"\n"
    )

    logged: Optional[bool] = None
    expected_moved: Optional[int] = None

    async def handler(step: Literal["log", "move"], mctx: MergeContext) -> None:
        nonlocal logged, expected_moved

        if step == "log":
            assert logged is None, "handler called twice for log step"
            logged = not not mctx.result.rows_affected

            if not logged:
                return

            await mctx.log.write(
                b"logged: true\n"
                b"interpretation: we logged that we intended to move some user_email_addresses "
                b"\ngoing to fetch details on what emails we should have transferred from the log entry\n"
            )

            conn = await itgs.conn()
            cursor = conn.cursor("weak")
            resp = await _log_and_execute_query(
                cursor,
                "SELECT reason FROM merge_account_log WHERE uid=?",
                (log_uid,),
                mctx.log,
            )
            assert resp.results, resp
            assert len(resp.results) == 1, resp
            assert len(resp.results[0]) == 1, resp

            parsed_reason = json.loads(resp.results[0][0])
            assert isinstance(parsed_reason, dict), resp
            await mctx.log.write(
                b"parsed_reason:\n"
                + json.dumps(parsed_reason, indent=2).encode("utf-8")
                + b"\n"
            )

            details = parsed_reason["context"]["transfered"]
            rows = parsed_reason["context"]["rows"]

            assert isinstance(details, list), resp
            assert isinstance(rows, int), resp
            assert len(details) == rows, resp
            assert rows > 0

            for detail in details:
                assert isinstance(detail, dict), resp
                email = detail.get("email")
                suppressed = detail.get("suppressed")
                verified = detail.get("verified")
                receives_notifications = detail.get("receives_notifications")
                assert isinstance(email, str), resp
                assert isinstance(suppressed, bool), resp
                assert isinstance(verified, bool), resp
                assert isinstance(receives_notifications, bool), resp

            expected_moved = rows
            await mctx.log.write(
                b"reason is correctly shaped for expected_moved="
                + str(expected_moved).encode("ascii")
                + b"\n"
            )
            return

        assert step == "move", step
        assert logged is not None, "move step handler called before log step"

        num_moved = mctx.result.rows_affected or 0
        await mctx.log.write(b"num_moved: " + str(num_moved).encode("ascii") + b"\n")
        if num_moved <= 0:
            assert (
                not logged
            ), f"logged that we intended to move some user_email_addresses, but none were moved"
        else:
            assert (
                logged
            ), f"moved some user_email_addresses, but didn't log that we intended to move any"
            assert expected_moved == num_moved, (
                f"logged that we intended to move {expected_moved}"
                f" user_email_addresses, but moved {num_moved}"
            )
        await mctx.log.write(b"log and move steps matched\n")

    ctes, ctes_qargs = _merging_user_and_original_user_ctes(octx)
    ctes += (
        ", query_ctx(id, email, suppressed, verified, receives_notifications) AS ("
        "SELECT"
        " user_email_addresses.id,"
        " user_email_addresses.email,"
        " EXISTS (SELECT 1 FROM suppressed_emails WHERE suppressed_emails.email_address = user_email_addresses.email COLLATE NOCASE),"
        " user_email_addresses.verified,"
        " user_email_addresses.receives_notifications "
        "FROM user_email_addresses, merging_user, original_user "
        "WHERE"
        "  user_email_addresses.user_id = merging_user.id"
        "  AND NOT EXISTS ("
        "   SELECT 1 FROM user_email_addresses AS uea"
        "   WHERE"
        "    uea.user_id = original_user.id"
        "    AND uea.email = user_email_addresses.email COLLATE NOCASE"
        "  )"
        ") "
    )
    return [
        MergeQuery(
            query=(
                f"{ctes}INSERT INTO merge_account_log ("
                " uid, user_id, operation_uid, operation_order, phase, step, step_result, reason, created_at"
                ") SELECT"
                " ?, original_user.id, ?, ?, 'merging', 'move_user_email_addresses__transfer', 'xfer',"
                " json_insert("
                "  '{}'"
                "  , '$.context.transfered', ("
                "   SELECT json_group_array("
                "    json_object("
                "     'email', email"
                "     , 'suppressed', json(iif(suppressed, 'true', 'false'))"
                "     , 'verified', json(iif(verified, 'true', 'false'))"
                "     , 'receives_notifications', json(iif(receives_notifications, 'true', 'false'))"
                "    ))"
                "   FROM query_ctx"
                "  )"
                "  , '$.context.rows', (SELECT COUNT(*) FROM query_ctx)"
                " ), ? "
                "FROM merging_user, original_user "
                "WHERE EXISTS (SELECT 1 FROM query_ctx)"
            ),
            qargs=[
                *ctes_qargs,
                log_uid,
                octx.operation_uid,
                OperationOrder.move_user_email_addresses__transfer.value,
                octx.merge_at,
            ],
            handler=partial(handler, "log"),
        ),
        MergeQuery(
            query=(
                f"{ctes}UPDATE user_email_addresses "
                "SET user_id = original_user.id "
                "FROM original_user "
                "WHERE"
                " EXISTS (SELECT 1 FROM query_ctx WHERE query_ctx.id = user_email_addresses.id)"
            ),
            qargs=[*ctes_qargs],
            handler=partial(handler, "move"),
        ),
    ]


async def _move_user_email_addresses__verify(
    itgs: Itgs,
    octx: _Ctx,
    /,
) -> Sequence[MergeQuery]:
    log_uid = f"oseh_mal_{secrets.token_urlsafe(16)}"
    await octx.log.write(
        b"- move_user_email_addresses__transfer -\n"
        b"computed:\n"
        b"  log_uid: " + log_uid.encode("ascii") + b"\n"
    )

    logged: Optional[bool] = None
    expected_verified: Optional[int] = None
    expected_verified_emails: Optional[List[str]] = None

    async def handler(step: Literal["log", "verify"], mctx: MergeContext) -> None:
        nonlocal logged, expected_verified, expected_verified_emails

        if step == "log":
            assert logged is None, "handler called twice for log step"
            logged = not not mctx.result.rows_affected

            if not logged:
                return

            await mctx.log.write(
                b"logged: true\n"
                b"interpretation: we logged that we intended to verify some user_email_addresses "
                b"\ngoing to fetch details on what emails we should have verified from the log entry\n"
            )

            conn = await itgs.conn()
            cursor = conn.cursor("weak")
            resp = await _log_and_execute_query(
                cursor,
                "SELECT reason FROM merge_account_log WHERE uid=?",
                (log_uid,),
                mctx.log,
            )
            assert resp.results, resp
            assert len(resp.results) == 1, resp
            assert len(resp.results[0]) == 1, resp

            parsed_reason = json.loads(resp.results[0][0])
            assert isinstance(parsed_reason, dict), resp
            await mctx.log.write(
                b"parsed_reason:\n"
                + json.dumps(parsed_reason, indent=2).encode("utf-8")
                + b"\n"
            )

            details = parsed_reason["context"]["verified"]
            rows = parsed_reason["context"]["rows"]

            assert isinstance(details, list), resp
            assert all(isinstance(s, str) for s in details), resp
            assert isinstance(rows, int), resp
            assert len(details) == rows, resp
            assert rows > 0

            expected_verified = rows
            expected_verified_emails = details
            await mctx.log.write(
                b"reason is correctly shaped for expected_verified="
                + str(expected_verified).encode("ascii")
                + b"\n"
            )
            return

        assert step == "verify", step
        assert logged is not None, "verify step handler called before log step"

        num_verified = mctx.result.rows_affected or 0
        await mctx.log.write(
            b"num_verified: " + str(num_verified).encode("ascii") + b"\n"
        )
        if num_verified <= 0:
            assert (
                not logged
            ), f"logged that we intended to verify some user_email_addresses, but none were verified"
        else:
            assert (
                logged
            ), f"verified some user_email_addresses, but didn't log that we intended to verify any"
            assert expected_verified == num_verified, (
                f"logged that we intended to verify {expected_verified}"
                f" user_email_addresses, but verified {num_verified}"
            )
            assert expected_verified_emails is not None

            conn = await itgs.conn()
            cursor = conn.cursor()
            for verified_email in expected_verified_emails:
                await mctx.log.write(
                    b"\nwriting contact method log for newly verified email: "
                    + verified_email.encode("utf-8")
                    + b"\n"
                )
                cml_uid = f"oseh_cml_{secrets.token_urlsafe(16)}"
                await mctx.log.write(
                    b"selected cml_uid: " + cml_uid.encode("ascii") + b"\n"
                )
                await _log_and_execute_query(
                    cursor,
                    f"INSERT INTO contact_method_log ("
                    " uid, user_id, channel, identifier, action, reason, created_at"
                    ") SELECT"
                    " ?, original_user.id, 'email', ?, 'verify', ?, ? "
                    "FROM users AS original_user "
                    "WHERE original_user.sub = ?",
                    (
                        cml_uid,
                        verified_email,
                        json.dumps(
                            {
                                "repo": "backend",
                                "file": __name__,
                                "context": {
                                    "merge_operation_uid": octx.operation_uid,
                                },
                            }
                        ),
                        octx.merge_at,
                        octx.original_user_sub,
                    ),
                    mctx.log,
                )
            await mctx.log.write(b"\nfinished writing contact method log entries\n")
        await mctx.log.write(b"log and verify steps matched\n")

    ctes, ctes_qargs = _merging_user_and_original_user_ctes(octx)
    ctes += (
        ", query_ctx(email) AS ("
        "SELECT"
        " user_email_addresses.email "
        "FROM user_email_addresses, merging_user, original_user "
        "WHERE"
        "  user_email_addresses.user_id = merging_user.id"
        "  AND user_email_addresses.verified"
        "  AND EXISTS ("
        "   SELECT 1 FROM user_email_addresses AS uea"
        "   WHERE"
        "    uea.user_id = original_user.id"
        "    AND uea.email = user_email_addresses.email COLLATE NOCASE"
        "    AND NOT uea.verified"
        "  )"
        ") "
    )
    return [
        MergeQuery(
            query=(
                f"{ctes}INSERT INTO merge_account_log ("
                " uid, user_id, operation_uid, operation_order, phase, step, step_result, reason, created_at"
                ") SELECT"
                " ?, original_user.id, ?, ?, 'merging', 'move_user_email_addresses__verify', 'xfer',"
                " json_insert("
                "  '{}'"
                "  , '$.context.verified', (SELECT json_group_array(email) FROM query_ctx)"
                "  , '$.context.rows', (SELECT COUNT(*) FROM query_ctx)"
                " ), ? "
                "FROM merging_user, original_user "
                "WHERE EXISTS (SELECT 1 FROM query_ctx)"
            ),
            qargs=[
                *ctes_qargs,
                log_uid,
                octx.operation_uid,
                OperationOrder.move_user_email_addresses__verify.value,
                octx.merge_at,
            ],
            handler=partial(handler, "log"),
        ),
        MergeQuery(
            query=(
                f"{ctes}UPDATE user_email_addresses "
                "SET verified = 1 "
                "WHERE"
                " EXISTS (SELECT 1 FROM original_user WHERE original_user.id = user_email_addresses.user_id)"
                " AND EXISTS (SELECT 1 FROM query_ctx WHERE query_ctx.email = user_email_addresses.email COLLATE NOCASE)"
            ),
            qargs=[*ctes_qargs],
            handler=partial(handler, "verify"),
        ),
    ]


async def _move_user_email_addresses__disable(
    itgs: Itgs, octx: _Ctx, /
) -> Sequence[MergeQuery]:
    if octx.email_hint is None:
        await octx.log.write(
            b"- move_user_email_addresses__disable -\n"
            b"no email hint, which means the only time we need to disable "
            b"emails is if there were enabled emails on both but there was no conflict "
            b"because user_daily_reminders was off on at least one of them. This is handled "
            b"by _move_user_email_addresses__disable_without_hint "
            b"which needs to occur before transferring emails.\n"
        )
        return []

    log_uid = f"oseh_mal_{secrets.token_urlsafe(16)}"
    await octx.log.write(
        b"- move_user_email_addresses__disable -\n"
        b"context:\n"
        b"  email_hint: " + octx.email_hint.encode("utf-8") + b"\n"
        b"computed:\n"
        b"  log_uid: " + log_uid.encode("ascii") + b"\n"
    )

    logged: Optional[bool] = None
    expected_disabled: Optional[int] = None
    expected_disabled_emails: Optional[List[str]] = None

    async def handler(step: Literal["log", "disable"], mctx: MergeContext) -> None:
        nonlocal logged, expected_disabled, expected_disabled_emails

        if step == "log":
            assert logged is None, "handler called twice for log step"
            logged = not not mctx.result.rows_affected

            if not logged:
                return

            await mctx.log.write(
                b"logged: true\n"
                b"interpretation: we logged that we intended to disable some user_email_addresses "
                b"\ngoing to fetch details on what emails we should have disabled from the log entry\n"
            )

            conn = await itgs.conn()
            cursor = conn.cursor("weak")
            resp = await _log_and_execute_query(
                cursor,
                "SELECT reason FROM merge_account_log WHERE uid=?",
                (log_uid,),
                mctx.log,
            )
            assert resp.results, resp
            assert len(resp.results) == 1, resp
            assert len(resp.results[0]) == 1, resp

            parsed_reason = json.loads(resp.results[0][0])
            assert isinstance(parsed_reason, dict), resp
            await mctx.log.write(
                b"parsed_reason:\n"
                + json.dumps(parsed_reason, indent=2).encode("utf-8")
                + b"\n"
            )

            details = parsed_reason["context"]["disabled"]
            rows = parsed_reason["context"]["rows"]

            assert isinstance(details, list), resp
            assert all(isinstance(s, str) for s in details), resp
            assert isinstance(rows, int), resp
            assert len(details) == rows, resp
            assert rows > 0

            expected_disabled = rows
            expected_disabled_emails = details
            await mctx.log.write(
                b"reason is correctly shaped for expected_disabled="
                + str(expected_disabled).encode("ascii")
                + b"\n"
            )
            return

        assert step == "disable", step
        assert logged is not None, "disable step handler called before log step"

        num_disabled = mctx.result.rows_affected or 0
        await mctx.log.write(
            b"num_disabled: " + str(num_disabled).encode("ascii") + b"\n"
        )
        if num_disabled <= 0:
            assert (
                not logged
            ), f"logged that we intended to disable some user_email_addresses, but none were disabled"
        else:
            assert (
                logged
            ), f"disabled some user_email_addresses, but didn't log that we intended to verify any"
            assert expected_disabled == num_disabled, (
                f"logged that we intended to disable {expected_disabled}"
                f" user_email_addresses, but disabled {num_disabled}"
            )
            assert expected_disabled_emails is not None

            conn = await itgs.conn()
            cursor = conn.cursor()
            for disabled_email in expected_disabled_emails:
                await mctx.log.write(
                    b"\nwriting contact method log for newly disabled email: "
                    + disabled_email.encode("utf-8")
                    + b"\n"
                )
                cml_uid = f"oseh_cml_{secrets.token_urlsafe(16)}"
                await mctx.log.write(
                    b"selected cml_uid: " + cml_uid.encode("ascii") + b"\n"
                )
                await _log_and_execute_query(
                    cursor,
                    f"INSERT INTO contact_method_log ("
                    " uid, user_id, channel, identifier, action, reason, created_at"
                    ") SELECT"
                    " ?, original_user.id, 'email', ?, 'disable_notifs', ?, ? "
                    "FROM users AS original_user "
                    "WHERE original_user.sub = ?",
                    (
                        cml_uid,
                        disabled_email,
                        json.dumps(
                            {
                                "repo": "backend",
                                "file": __name__,
                                "context": {
                                    "merge_operation_uid": octx.operation_uid,
                                },
                            }
                        ),
                        octx.merge_at,
                        octx.original_user_sub,
                    ),
                    mctx.log,
                )
            await mctx.log.write(b"\nfinished writing contact method log entries\n")
        await mctx.log.write(b"log and disable steps matched\n")

    ctes, ctes_qargs = _merging_user_and_original_user_ctes(octx)
    ctes += (
        ", query_ctx(email) AS ("
        "SELECT"
        " user_email_addresses.email "
        "FROM user_email_addresses, original_user "
        "WHERE"
        "  user_email_addresses.user_id = original_user.id"
        "  AND user_email_addresses.email <> ? COLLATE NOCASE"
        "  AND user_email_addresses.receives_notifications"
        ") "
    )
    ctes_qargs.append(octx.email_hint)
    return [
        MergeQuery(
            query=(
                f"{ctes}INSERT INTO merge_account_log ("
                " uid, user_id, operation_uid, operation_order, phase, step, step_result, reason, created_at"
                ") SELECT"
                " ?, original_user.id, ?, ?, 'merging', 'move_user_email_addresses__disable', 'xfer',"
                " json_insert("
                "  '{}'"
                "  , '$.context.disabled', (SELECT json_group_array(email) FROM query_ctx)"
                "  , '$.context.rows', (SELECT COUNT(*) FROM query_ctx)"
                " ), ? "
                "FROM merging_user, original_user "
                "WHERE EXISTS (SELECT 1 FROM query_ctx)"
            ),
            qargs=[
                *ctes_qargs,
                log_uid,
                octx.operation_uid,
                OperationOrder.move_user_email_addresses__disable.value,
                octx.merge_at,
            ],
            handler=partial(handler, "log"),
        ),
        MergeQuery(
            query=(
                f"{ctes}UPDATE user_email_addresses "
                "SET receives_notifications = 0 "
                "WHERE"
                " EXISTS (SELECT 1 FROM original_user WHERE original_user.id = user_email_addresses.user_id)"
                " AND EXISTS (SELECT 1 FROM query_ctx WHERE query_ctx.email = user_email_addresses.email COLLATE NOCASE)"
            ),
            qargs=[*ctes_qargs],
            handler=partial(handler, "disable"),
        ),
    ]


class _MoveUserEmailAddressesDisableWithoutHintContext(BaseModel):
    original_enabled: List[str] = Field()
    merging_enabled: List[str] = Field()
    original_receives_reminders: bool = Field()
    merging_receives_reminders: bool = Field()
    disabling_merging_emails: bool = Field()
    disabling_original_emails: bool = Field()


class _MoveUserEmailAddressesDisableWithoutHintReason(BaseModel):
    context: _MoveUserEmailAddressesDisableWithoutHintContext = Field()


async def _move_user_email_addresses__disable_without_hint(
    itgs: Itgs, octx: _Ctx, /
) -> Sequence[MergeQuery]:
    if octx.email_hint is not None:
        await octx.log.write(
            b"- move_user_email_addresses__disable_without_hint -\n"
            b"an email hint is available so we don't need this step\n"
        )
        return []

    log_uid = f"oseh_mal_{secrets.token_urlsafe(16)}"
    await octx.log.write(
        b"- move_user_email_addresses__disable_without_hint -\n"
        b"computed:\n"
        b"  log_uid: " + log_uid.encode("ascii") + b"\n"
    )

    logged: Optional[bool] = None
    expected_disabled: Optional[int] = None
    expected_disabled_emails: Optional[List[str]] = None

    async def handler(step: Literal["log", "disable"], mctx: MergeContext) -> None:
        nonlocal logged, expected_disabled, expected_disabled_emails

        if step == "log":
            assert logged is None, "handler called twice for log step"
            logged = not not mctx.result.rows_affected

            if not logged:
                return

            await mctx.log.write(
                b"logged: true\n"
                b"interpretation: we logged that we intended to disable some user_email_addresses "
                b"\ngoing to fetch details on what emails we should have disabled from the log entry\n"
            )

            conn = await itgs.conn()
            cursor = conn.cursor("weak")
            resp = await _log_and_execute_query(
                cursor,
                "SELECT reason FROM merge_account_log WHERE uid=?",
                (log_uid,),
                mctx.log,
            )
            assert resp.results, resp
            assert len(resp.results) == 1, resp
            assert len(resp.results[0]) == 1, resp

            parsed_reason_schemaless = json.loads(resp.results[0][0])
            assert isinstance(parsed_reason_schemaless, dict), resp
            await mctx.log.write(
                b"parsed_reason_schemaless:\n"
                + json.dumps(parsed_reason_schemaless, indent=2).encode("utf-8")
                + b"\n"
            )

            parsed_reason = (
                _MoveUserEmailAddressesDisableWithoutHintReason.model_validate_json(
                    resp.results[0][0]
                )
            )
            await mctx.log.write(
                b"parsed_reason:\n"
                + _MoveUserEmailAddressesDisableWithoutHintReason.__pydantic_serializer__.to_json(
                    parsed_reason, indent=2
                )
                + b"\n"
            )

            expected_disabled_emails = []
            if parsed_reason.context.disabling_merging_emails:
                expected_disabled_emails.extend(parsed_reason.context.merging_enabled)
            if parsed_reason.context.disabling_original_emails:
                expected_disabled_emails.extend(parsed_reason.context.original_enabled)

            expected_disabled = len(expected_disabled_emails)
            await mctx.log.write(
                b"expected_disabled_emails:\n"
                + json.dumps(expected_disabled_emails, indent=2).encode("utf-8")
                + b"\n"
                b"expected_disabled: " + str(expected_disabled).encode("ascii") + b"\n"
            )
            return

        assert step == "disable", step
        assert logged is not None, "disable step handler called before log step"

        num_disabled = mctx.result.rows_affected or 0
        await mctx.log.write(
            b"num_disabled: " + str(num_disabled).encode("ascii") + b"\n"
        )
        if num_disabled <= 0:
            assert (
                not logged
            ), f"logged that we intended to disable some user_email_addresses, but none were disabled"
        else:
            assert (
                logged
            ), f"disabled some user_email_addresses, but didn't log that we intended to verify any"
            assert expected_disabled == num_disabled, (
                f"logged that we intended to disable {expected_disabled}"
                f" user_email_addresses, but disabled {num_disabled}"
            )
            assert expected_disabled_emails is not None

            conn = await itgs.conn()
            cursor = conn.cursor()
            for disabled_email in expected_disabled_emails:
                await mctx.log.write(
                    b"\nwriting contact method log for newly disabled email: "
                    + disabled_email.encode("utf-8")
                    + b"\n"
                )
                cml_uid = f"oseh_cml_{secrets.token_urlsafe(16)}"
                await mctx.log.write(
                    b"selected cml_uid: " + cml_uid.encode("ascii") + b"\n"
                )
                await _log_and_execute_query(
                    cursor,
                    f"INSERT INTO contact_method_log ("
                    " uid, user_id, channel, identifier, action, reason, created_at"
                    ") SELECT"
                    " ?, original_user.id, 'email', ?, 'disable_notifs', ?, ? "
                    "FROM users AS original_user "
                    "WHERE original_user.sub = ?",
                    (
                        cml_uid,
                        disabled_email,
                        json.dumps(
                            {
                                "repo": "backend",
                                "file": __name__,
                                "context": {
                                    "merge_operation_uid": octx.operation_uid,
                                },
                            }
                        ),
                        octx.merge_at,
                        octx.original_user_sub,
                    ),
                    mctx.log,
                )
            await mctx.log.write(b"\nfinished writing contact method log entries\n")
        await mctx.log.write(b"log and disable steps matched\n")

    ctes, ctes_qargs = _merging_user_and_original_user_ctes(octx)
    ctes += (
        ", original_emails(id, email) AS ("
        "SELECT"
        " user_email_addresses.id, user_email_addresses.email "
        "FROM user_email_addresses, original_user "
        "WHERE"
        " user_email_addresses.user_id = original_user.id"
        " AND user_email_addresses.receives_notifications"
        "), merging_emails(id, email) AS ("
        "SELECT"
        " user_email_addresses.id, user_email_addresses.email "
        "FROM user_email_addresses, merging_user "
        "WHERE"
        " user_email_addresses.user_id = merging_user.id"
        " AND user_email_addresses.receives_notifications"
        "), query_ctx_1(original_receives_reminders, merging_receives_reminders) AS ("
        "SELECT"
        " EXISTS (SELECT 1 FROM user_daily_reminders, original_user WHERE user_daily_reminders.user_id = original_user.id AND user_daily_reminders.channel = 'email' AND user_daily_reminders.day_of_week_mask <> 0),"
        " EXISTS (SELECT 1 FROM user_daily_reminders, merging_user WHERE user_daily_reminders.user_id = merging_user.id AND user_daily_reminders.channel = 'email' AND user_daily_reminders.day_of_week_mask <> 0)"
        "), query_ctx_2(disabling_merging_emails, disabling_original_emails) AS ("
        "SELECT"
        " ("
        "  EXISTS (SELECT 1 FROM original_emails)"
        "  AND EXISTS (SELECT 1 FROM merging_emails)"
        "  AND query_ctx_1.original_receives_reminders"
        " ),"
        " ("
        "  EXISTS (SELECT 1 FROM original_emails)"
        "  AND EXISTS (SELECT 1 FROM merging_emails)"
        "  AND NOT query_ctx_1.original_receives_reminders"
        " ) "
        "FROM query_ctx_1"
        ") "
    )
    return [
        MergeQuery(
            query=(
                f"{ctes}INSERT INTO merge_account_log ("
                " uid, user_id, operation_uid, operation_order, phase, step, step_result, reason, created_at"
                ") SELECT"
                " ?, original_user.id, ?, ?, 'merging', 'move_user_email_addresses__disable_without_hint', 'xfer',"
                " json_insert('{}'"
                " , '$.context.original_enabled', (SELECT json_group_array(email) FROM original_emails)"
                " , '$.context.merging_enabled', (SELECT json_group_array(email) FROM merging_emails)"
                " , '$.context.original_receives_reminders', json(iif(query_ctx_1.original_receives_reminders, 'true', 'false'))"
                " , '$.context.merging_receives_reminders', json(iif(query_ctx_1.merging_receives_reminders, 'true', 'false'))"
                " , '$.context.disabling_merging_emails', json(iif(query_ctx_2.disabling_merging_emails, 'true', 'false'))"
                " , '$.context.disabling_original_emails', json(iif(query_ctx_2.disabling_original_emails, 'true', 'false'))"
                " ), ? "
                "FROM merging_user, original_user, query_ctx_1, query_ctx_2 "
                "WHERE"
                " query_ctx_2.disabling_merging_emails OR query_ctx_2.disabling_original_emails"
            ),
            qargs=[
                *ctes_qargs,
                log_uid,
                octx.operation_uid,
                OperationOrder.move_user_email_addresses__disable_without_hint.value,
                octx.merge_at,
            ],
            handler=partial(handler, "log"),
        ),
        MergeQuery(
            query=(
                f"{ctes}UPDATE user_email_addresses "
                "SET receives_notifications = 0 "
                "WHERE"
                " ("
                "  EXISTS (SELECT 1 FROM query_ctx_2 WHERE query_ctx_2.disabling_merging_emails)"
                "  AND EXISTS (SELECT 1 FROM merging_emails WHERE merging_emails.id = user_email_addresses.id)"
                " )"
                " OR ("
                "  EXISTS (SELECT 1 FROM query_ctx_2 WHERE query_ctx_2.disabling_original_emails)"
                "  AND EXISTS (SELECT 1 FROM original_emails WHERE original_emails.id = user_email_addresses.id)"
                " )"
            ),
            qargs=[*ctes_qargs],
            handler=partial(handler, "disable"),
        ),
    ]


async def _move_user_likes(itgs: Itgs, octx: _Ctx, /) -> Sequence[MergeQuery]:
    log_uid = f"oseh_mal_{secrets.token_urlsafe(16)}"
    await octx.log.write(
        b"- move_user_likes -\n"
        b"computed:\n"
        b"  log_uid: " + log_uid.encode("ascii") + b"\n"
    )

    handler = await _create_simple_handler(itgs, octx, "user_likes", log_uid=log_uid)
    ctes, ctes_qargs = _merging_user_and_original_user_ctes(octx)
    return [
        MergeQuery(
            query=(
                f"{ctes}, query_ctx(rows) AS ("
                f"SELECT"
                " COUNT(*) "
                "FROM user_likes, merging_user "
                "WHERE"
                " user_likes.user_id = merging_user.id"
                " AND NOT EXISTS ("
                "  SELECT 1 FROM user_likes AS ul, original_user"
                "  WHERE"
                "   ul.user_id = original_user.id"
                "   AND ul.journey_id = user_likes.journey_id"
                " )"
                ") INSERT INTO merge_account_log ("
                " uid, user_id, operation_uid, operation_order, phase, step, step_result, reason, created_at"
                ") SELECT"
                " ?, original_user.id, ?, ?, 'merging', 'move_user_likes', 'xfer', json_insert('{}', '$.context.rows', query_ctx.rows), ? "
                "FROM merging_user, original_user, query_ctx "
                "WHERE query_ctx.rows > 0"
            ),
            qargs=[
                *ctes_qargs,
                log_uid,
                octx.operation_uid,
                OperationOrder.move_user_likes.value,
                octx.merge_at,
            ],
            handler=partial(handler, "log"),
        ),
        MergeQuery(
            query=(
                f"{ctes}UPDATE user_likes "
                "SET user_id = original_user.id "
                "FROM original_user, merging_user "
                "WHERE"
                " user_likes.user_id = merging_user.id"
                " AND NOT EXISTS ("
                "  SELECT 1 FROM user_likes AS ul"
                "  WHERE"
                "   ul.user_id = original_user.id"
                "   AND ul.journey_id = user_likes.journey_id"
                " )"
            ),
            qargs=[*ctes_qargs],
            handler=partial(handler, "move"),
        ),
    ]


class _MoveUserPhoneNumbersDisableWithoutHintContext(BaseModel):
    original_enabled: List[str] = Field()
    merging_enabled: List[str] = Field()
    original_receives_reminders: bool = Field()
    merging_receives_reminders: bool = Field()
    disabling_merging_phones: bool = Field()
    disabling_original_phones: bool = Field()


class _MoveUserPhoneNumbersDisableWithoutHintReason(BaseModel):
    context: _MoveUserPhoneNumbersDisableWithoutHintContext = Field()


async def _move_user_phone_numbers__disable_without_hint(
    itgs: Itgs, octx: _Ctx, /
) -> Sequence[MergeQuery]:
    if octx.phone_hint is not None:
        await octx.log.write(
            b"- move_user_phone_numbers__disable_without_hint -\n"
            b"a phone hint is available so we don't need this step\n"
        )
        return []

    log_uid = f"oseh_mal_{secrets.token_urlsafe(16)}"
    await octx.log.write(
        b"- move_user_phone_numbers__disable_without_hint -\n"
        b"computed:\n"
        b"  log_uid: " + log_uid.encode("ascii") + b"\n"
    )

    logged: Optional[bool] = None
    expected_disabled: Optional[int] = None
    expected_disabled_phones: Optional[List[str]] = None

    async def handler(step: Literal["log", "disable"], mctx: MergeContext) -> None:
        nonlocal logged, expected_disabled, expected_disabled_phones

        if step == "log":
            assert logged is None, "handler called twice for log step"
            logged = not not mctx.result.rows_affected

            if not logged:
                return

            await mctx.log.write(
                b"logged: true\n"
                b"interpretation: we logged that we intended to disable some user_phone_numbers "
                b"\ngoing to fetch details on what phones we should have disabled from the log entry\n"
            )

            conn = await itgs.conn()
            cursor = conn.cursor("weak")
            resp = await _log_and_execute_query(
                cursor,
                "SELECT reason FROM merge_account_log WHERE uid=?",
                (log_uid,),
                mctx.log,
            )
            assert resp.results, resp
            assert len(resp.results) == 1, resp
            assert len(resp.results[0]) == 1, resp

            parsed_reason_schemaless = json.loads(resp.results[0][0])
            assert isinstance(parsed_reason_schemaless, dict), resp
            await mctx.log.write(
                b"parsed_reason_schemaless:\n"
                + json.dumps(parsed_reason_schemaless, indent=2).encode("utf-8")
                + b"\n"
            )

            parsed_reason = (
                _MoveUserPhoneNumbersDisableWithoutHintReason.model_validate_json(
                    resp.results[0][0]
                )
            )
            await mctx.log.write(
                b"parsed_reason:\n"
                + _MoveUserPhoneNumbersDisableWithoutHintReason.__pydantic_serializer__.to_json(
                    parsed_reason, indent=2
                )
                + b"\n"
            )

            expected_disabled_phones = []
            if parsed_reason.context.disabling_merging_phones:
                expected_disabled_phones.extend(parsed_reason.context.merging_enabled)
            if parsed_reason.context.disabling_original_phones:
                expected_disabled_phones.extend(parsed_reason.context.original_enabled)

            expected_disabled = len(expected_disabled_phones)
            await mctx.log.write(
                b"expected_disabled_phones:\n"
                + json.dumps(expected_disabled_phones, indent=2).encode("utf-8")
                + b"\n"
                b"expected_disabled: " + str(expected_disabled).encode("ascii") + b"\n"
            )
            return

        assert step == "disable", step
        assert logged is not None, "disable step handler called before log step"

        num_disabled = mctx.result.rows_affected or 0
        await mctx.log.write(
            b"num_disabled: " + str(num_disabled).encode("ascii") + b"\n"
        )
        if num_disabled <= 0:
            assert (
                not logged
            ), f"logged that we intended to disable some user_phone_numbers, but none were disabled"
        else:
            assert (
                logged
            ), f"disabled some user_phone_numbers, but didn't log that we intended to verify any"
            assert expected_disabled == num_disabled, (
                f"logged that we intended to disable {expected_disabled}"
                f" user_phone_numbers, but disabled {num_disabled}"
            )
            assert expected_disabled_phones is not None

            conn = await itgs.conn()
            cursor = conn.cursor()
            for disabled_phone in expected_disabled_phones:
                await mctx.log.write(
                    b"\nwriting contact method log for newly disabled phone: "
                    + disabled_phone.encode("utf-8")
                    + b"\n"
                )
                cml_uid = f"oseh_cml_{secrets.token_urlsafe(16)}"
                await mctx.log.write(
                    b"selected cml_uid: " + cml_uid.encode("ascii") + b"\n"
                )
                await _log_and_execute_query(
                    cursor,
                    f"INSERT INTO contact_method_log ("
                    " uid, user_id, channel, identifier, action, reason, created_at"
                    ") SELECT"
                    " ?, original_user.id, 'phone', ?, 'disable_notifs', ?, ? "
                    "FROM users AS original_user "
                    "WHERE original_user.sub = ?",
                    (
                        cml_uid,
                        disabled_phone,
                        json.dumps(
                            {
                                "repo": "backend",
                                "file": __name__,
                                "context": {
                                    "merge_operation_uid": octx.operation_uid,
                                },
                            }
                        ),
                        octx.merge_at,
                        octx.original_user_sub,
                    ),
                    mctx.log,
                )
            await mctx.log.write(b"\nfinished writing contact method log entries\n")
        await mctx.log.write(b"log and disable steps matched\n")

    ctes, ctes_qargs = _merging_user_and_original_user_ctes(octx)
    ctes += (
        ", original_phones(id, phone) AS ("
        "SELECT"
        " user_phone_numbers.id, user_phone_numbers.phone_number "
        "FROM user_phone_numbers, original_user "
        "WHERE"
        " user_phone_numbers.user_id = original_user.id"
        " AND user_phone_numbers.receives_notifications"
        "), merging_phones(id, phone) AS ("
        "SELECT"
        " user_phone_numbers.id, user_phone_numbers.phone_number "
        "FROM user_phone_numbers, merging_user "
        "WHERE"
        " user_phone_numbers.user_id = merging_user.id"
        " AND user_phone_numbers.receives_notifications"
        "), query_ctx_1(original_receives_reminders, merging_receives_reminders) AS ("
        "SELECT"
        " EXISTS (SELECT 1 FROM user_daily_reminders, original_user WHERE user_daily_reminders.user_id = original_user.id AND user_daily_reminders.channel = 'sms' AND user_daily_reminders.day_of_week_mask <> 0),"
        " EXISTS (SELECT 1 FROM user_daily_reminders, merging_user WHERE user_daily_reminders.user_id = merging_user.id AND user_daily_reminders.channel = 'sms' AND user_daily_reminders.day_of_week_mask <> 0)"
        "), query_ctx_2(disabling_merging_phones, disabling_original_phones) AS ("
        "SELECT"
        " ("
        "  EXISTS (SELECT 1 FROM original_phones)"
        "  AND EXISTS (SELECT 1 FROM merging_phones)"
        "  AND query_ctx_1.original_receives_reminders"
        " ),"
        " ("
        "  EXISTS (SELECT 1 FROM original_phones)"
        "  AND EXISTS (SELECT 1 FROM merging_phones)"
        "  AND NOT query_ctx_1.original_receives_reminders"
        " ) "
        "FROM query_ctx_1"
        ") "
    )
    return [
        MergeQuery(
            query=(
                f"{ctes}INSERT INTO merge_account_log ("
                " uid, user_id, operation_uid, operation_order, phase, step, step_result, reason, created_at"
                ") SELECT"
                " ?, original_user.id, ?, ?, 'merging', 'move_user_phone_numbers__disable_without_hint', 'xfer',"
                " json_insert('{}'"
                " , '$.context.original_enabled', (SELECT json_group_array(phone) FROM original_phones)"
                " , '$.context.merging_enabled', (SELECT json_group_array(phone) FROM merging_phones)"
                " , '$.context.original_receives_reminders', json(iif(query_ctx_1.original_receives_reminders, 'true', 'false'))"
                " , '$.context.merging_receives_reminders', json(iif(query_ctx_1.merging_receives_reminders, 'true', 'false'))"
                " , '$.context.disabling_merging_phones', json(iif(query_ctx_2.disabling_merging_phones, 'true', 'false'))"
                " , '$.context.disabling_original_phones', json(iif(query_ctx_2.disabling_original_phones, 'true', 'false'))"
                " ), ? "
                "FROM merging_user, original_user, query_ctx_1, query_ctx_2 "
                "WHERE"
                " query_ctx_2.disabling_merging_phones OR query_ctx_2.disabling_original_phones"
            ),
            qargs=[
                *ctes_qargs,
                log_uid,
                octx.operation_uid,
                OperationOrder.move_user_email_addresses__disable_without_hint.value,
                octx.merge_at,
            ],
            handler=partial(handler, "log"),
        ),
        MergeQuery(
            query=(
                f"{ctes}UPDATE user_phone_numbers "
                "SET receives_notifications = 0 "
                "WHERE"
                " ("
                "  EXISTS (SELECT 1 FROM query_ctx_2 WHERE query_ctx_2.disabling_merging_phones)"
                "  AND EXISTS (SELECT 1 FROM merging_phones WHERE merging_phones.id = user_phone_numbers.id)"
                " )"
                " OR ("
                "  EXISTS (SELECT 1 FROM query_ctx_2 WHERE query_ctx_2.disabling_original_phones)"
                "  AND EXISTS (SELECT 1 FROM original_phones WHERE original_phones.id = user_phone_numbers.id)"
                " )"
            ),
            qargs=[*ctes_qargs],
            handler=partial(handler, "disable"),
        ),
    ]


async def _move_user_phone_numbers__transfer(
    itgs: Itgs,
    octx: _Ctx,
    /,
) -> Sequence[MergeQuery]:
    log_uid = f"oseh_mal_{secrets.token_urlsafe(16)}"
    await octx.log.write(
        b"- move_user_phone_numbers__transfer -\n"
        b"computed:\n"
        b"  log_uid: " + log_uid.encode("ascii") + b"\n"
    )

    logged: Optional[bool] = None
    expected_moved: Optional[int] = None

    async def handler(step: Literal["log", "move"], mctx: MergeContext) -> None:
        nonlocal logged, expected_moved

        if step == "log":
            assert logged is None, "handler called twice for log step"
            logged = not not mctx.result.rows_affected

            if not logged:
                return

            await mctx.log.write(
                b"logged: true\n"
                b"interpretation: we logged that we intended to move some user_phone_numbers "
                b"\ngoing to fetch details on what phone numbers we should have transferred from the log entry\n"
            )

            conn = await itgs.conn()
            cursor = conn.cursor("weak")
            resp = await _log_and_execute_query(
                cursor,
                "SELECT reason FROM merge_account_log WHERE uid=?",
                (log_uid,),
                mctx.log,
            )
            assert resp.results, resp
            assert len(resp.results) == 1, resp
            assert len(resp.results[0]) == 1, resp

            parsed_reason = json.loads(resp.results[0][0])
            assert isinstance(parsed_reason, dict), resp
            await mctx.log.write(
                b"parsed_reason:\n"
                + json.dumps(parsed_reason, indent=2).encode("utf-8")
                + b"\n"
            )

            details = parsed_reason["context"]["transfered"]
            rows = parsed_reason["context"]["rows"]

            assert isinstance(details, list), resp
            assert isinstance(rows, int), resp
            assert len(details) == rows, resp
            assert rows > 0

            for detail in details:
                assert isinstance(detail, dict), resp
                phone = detail.get("phone")
                suppressed = detail.get("suppressed")
                verified = detail.get("verified")
                receives_notifications = detail.get("receives_notifications")
                assert isinstance(phone, str), resp
                assert isinstance(suppressed, bool), resp
                assert isinstance(verified, bool), resp
                assert isinstance(receives_notifications, bool), resp

            expected_moved = rows
            await mctx.log.write(
                b"reason is correctly shaped for expected_moved="
                + str(expected_moved).encode("ascii")
                + b"\n"
            )
            return

        assert step == "move", step
        assert logged is not None, "move step handler called before log step"

        num_moved = mctx.result.rows_affected or 0
        await mctx.log.write(b"num_moved: " + str(num_moved).encode("ascii") + b"\n")
        if num_moved <= 0:
            assert (
                not logged
            ), f"logged that we intended to move some user_phone_numbers, but none were moved"
        else:
            assert (
                logged
            ), f"moved some user_phone_numbers, but didn't log that we intended to move any"
            assert expected_moved == num_moved, (
                f"logged that we intended to move {expected_moved}"
                f" user_phone_numbers, but moved {num_moved}"
            )
        await mctx.log.write(b"log and move steps matched\n")

    ctes, ctes_qargs = _merging_user_and_original_user_ctes(octx)
    ctes += (
        ", query_ctx(id, phone, suppressed, verified, receives_notifications) AS ("
        "SELECT"
        " user_phone_numbers.id,"
        " user_phone_numbers.phone_number,"
        " EXISTS (SELECT 1 FROM suppressed_phone_numbers WHERE suppressed_phone_numbers.phone_number = user_phone_numbers.phone_number),"
        " user_phone_numbers.verified,"
        " user_phone_numbers.receives_notifications "
        "FROM user_phone_numbers, merging_user, original_user "
        "WHERE"
        "  user_phone_numbers.user_id = merging_user.id"
        "  AND NOT EXISTS ("
        "   SELECT 1 FROM user_phone_numbers AS upn"
        "   WHERE"
        "    upn.user_id = original_user.id"
        "    AND upn.phone_number = user_phone_numbers.phone_number"
        "  )"
        ") "
    )
    return [
        MergeQuery(
            query=(
                f"{ctes}INSERT INTO merge_account_log ("
                " uid, user_id, operation_uid, operation_order, phase, step, step_result, reason, created_at"
                ") SELECT"
                " ?, original_user.id, ?, ?, 'merging', 'move_user_phone_numbers__transfer', 'xfer',"
                " json_insert("
                "  '{}'"
                "  , '$.context.transfered', ("
                "   SELECT json_group_array("
                "    json_object("
                "     'phone', phone"
                "     , 'suppressed', json(iif(suppressed, 'true', 'false'))"
                "     , 'verified', json(iif(verified, 'true', 'false'))"
                "     , 'receives_notifications', json(iif(receives_notifications, 'true', 'false'))"
                "    ))"
                "   FROM query_ctx"
                "  )"
                "  , '$.context.rows', (SELECT COUNT(*) FROM query_ctx)"
                " ), ? "
                "FROM merging_user, original_user "
                "WHERE EXISTS (SELECT 1 FROM query_ctx)"
            ),
            qargs=[
                *ctes_qargs,
                log_uid,
                octx.operation_uid,
                OperationOrder.move_user_phone_numbers__transfer.value,
                octx.merge_at,
            ],
            handler=partial(handler, "log"),
        ),
        MergeQuery(
            query=(
                f"{ctes}UPDATE user_phone_numbers "
                "SET user_id = original_user.id "
                "FROM original_user "
                "WHERE"
                " EXISTS (SELECT 1 FROM query_ctx WHERE query_ctx.id = user_phone_numbers.id)"
            ),
            qargs=[*ctes_qargs],
            handler=partial(handler, "move"),
        ),
    ]


async def _move_user_phone_numbers__verify(
    itgs: Itgs,
    octx: _Ctx,
    /,
) -> Sequence[MergeQuery]:
    log_uid = f"oseh_mal_{secrets.token_urlsafe(16)}"
    await octx.log.write(
        b"- move_user_phone_numbers__transfer -\n"
        b"computed:\n"
        b"  log_uid: " + log_uid.encode("ascii") + b"\n"
    )

    logged: Optional[bool] = None
    expected_verified: Optional[int] = None
    expected_verified_phones: Optional[List[str]] = None

    async def handler(step: Literal["log", "verify"], mctx: MergeContext) -> None:
        nonlocal logged, expected_verified, expected_verified_phones

        if step == "log":
            assert logged is None, "handler called twice for log step"
            logged = not not mctx.result.rows_affected

            if not logged:
                return

            await mctx.log.write(
                b"logged: true\n"
                b"interpretation: we logged that we intended to verify some user_phone_numbers "
                b"\ngoing to fetch details on what emails we should have verified from the log entry\n"
            )

            conn = await itgs.conn()
            cursor = conn.cursor("weak")
            resp = await _log_and_execute_query(
                cursor,
                "SELECT reason FROM merge_account_log WHERE uid=?",
                (log_uid,),
                mctx.log,
            )
            assert resp.results, resp
            assert len(resp.results) == 1, resp
            assert len(resp.results[0]) == 1, resp

            parsed_reason = json.loads(resp.results[0][0])
            assert isinstance(parsed_reason, dict), resp
            await mctx.log.write(
                b"parsed_reason:\n"
                + json.dumps(parsed_reason, indent=2).encode("utf-8")
                + b"\n"
            )

            details = parsed_reason["context"]["verified"]
            rows = parsed_reason["context"]["rows"]

            assert isinstance(details, list), resp
            assert all(isinstance(s, str) for s in details), resp
            assert isinstance(rows, int), resp
            assert len(details) == rows, resp
            assert rows > 0

            expected_verified = rows
            expected_verified_phones = details
            await mctx.log.write(
                b"reason is correctly shaped for expected_verified="
                + str(expected_verified).encode("ascii")
                + b"\n"
            )
            return

        assert step == "verify", step
        assert logged is not None, "verify step handler called before log step"

        num_verified = mctx.result.rows_affected or 0
        await mctx.log.write(
            b"num_verified: " + str(num_verified).encode("ascii") + b"\n"
        )
        if num_verified <= 0:
            assert (
                not logged
            ), f"logged that we intended to verify some user_phone_numbers, but none were verified"
        else:
            assert (
                logged
            ), f"verified some user_phone_numbers, but didn't log that we intended to verify any"
            assert expected_verified == num_verified, (
                f"logged that we intended to verify {expected_verified}"
                f" user_phone_numbers, but verified {num_verified}"
            )
            assert expected_verified_phones is not None

            conn = await itgs.conn()
            cursor = conn.cursor()
            for verified_phone in expected_verified_phones:
                await mctx.log.write(
                    b"\nwriting contact method log for newly verified phone: "
                    + verified_phone.encode("utf-8")
                    + b"\n"
                )
                cml_uid = f"oseh_cml_{secrets.token_urlsafe(16)}"
                await mctx.log.write(
                    b"selected cml_uid: " + cml_uid.encode("ascii") + b"\n"
                )
                await _log_and_execute_query(
                    cursor,
                    f"INSERT INTO contact_method_log ("
                    " uid, user_id, channel, identifier, action, reason, created_at"
                    ") SELECT"
                    " ?, original_user.id, 'phone', ?, 'verify', ?, ? "
                    "FROM users AS original_user "
                    "WHERE original_user.sub = ?",
                    (
                        cml_uid,
                        verified_phone,
                        json.dumps(
                            {
                                "repo": "backend",
                                "file": __name__,
                                "context": {
                                    "merge_operation_uid": octx.operation_uid,
                                },
                            }
                        ),
                        octx.merge_at,
                        octx.original_user_sub,
                    ),
                    mctx.log,
                )
            await mctx.log.write(b"\nfinished writing contact method log entries\n")
        await mctx.log.write(b"log and verify steps matched\n")

    ctes, ctes_qargs = _merging_user_and_original_user_ctes(octx)
    ctes += (
        ", query_ctx(phone) AS ("
        "SELECT"
        " user_phone_numbers.phone_number "
        "FROM user_phone_numbers, merging_user, original_user "
        "WHERE"
        "  user_phone_numbers.user_id = merging_user.id"
        "  AND user_phone_numbers.verified"
        "  AND EXISTS ("
        "   SELECT 1 FROM user_phone_numbers AS upn"
        "   WHERE"
        "    upn.user_id = original_user.id"
        "    AND upn.phone_number = user_phone_numbers.phone_number COLLATE NOCASE"
        "    AND NOT upn.verified"
        "  )"
        ") "
    )
    return [
        MergeQuery(
            query=(
                f"{ctes}INSERT INTO merge_account_log ("
                " uid, user_id, operation_uid, operation_order, phase, step, step_result, reason, created_at"
                ") SELECT"
                " ?, original_user.id, ?, ?, 'merging', 'move_user_phone_numbers__verify', 'xfer',"
                " json_insert("
                "  '{}'"
                "  , '$.context.verified', (SELECT json_group_array(phone) FROM query_ctx)"
                "  , '$.context.rows', (SELECT COUNT(*) FROM query_ctx)"
                " ), ? "
                "FROM merging_user, original_user "
                "WHERE EXISTS (SELECT 1 FROM query_ctx)"
            ),
            qargs=[
                *ctes_qargs,
                log_uid,
                octx.operation_uid,
                OperationOrder.move_user_phone_numbers__verify.value,
                octx.merge_at,
            ],
            handler=partial(handler, "log"),
        ),
        MergeQuery(
            query=(
                f"{ctes}UPDATE user_phone_numbers "
                "SET verified = 1 "
                "WHERE"
                " EXISTS (SELECT 1 FROM original_user WHERE original_user.id = user_phone_numbers.user_id)"
                " AND EXISTS (SELECT 1 FROM query_ctx WHERE query_ctx.phone = user_phone_numbers.phone_number)"
            ),
            qargs=[*ctes_qargs],
            handler=partial(handler, "verify"),
        ),
    ]


async def _move_user_phone_numbers__disable(
    itgs: Itgs, octx: _Ctx, /
) -> Sequence[MergeQuery]:
    if octx.phone_hint is None:
        await octx.log.write(
            b"- move_user_phone_numbers__disable -\n"
            b"no phone hint, which means the only time we need to disable "
            b"phones is if there were enabled phone numbers on both "
            b"but there was no conflict because user_daily_reminders was off on at least "
            b"one of them. This is handled by _move_user_phone_numbers__disable_without_hint "
            b"which needs to occur before transferring phones.\n"
        )
        return []

    log_uid = f"oseh_mal_{secrets.token_urlsafe(16)}"
    await octx.log.write(
        b"- move_user_phone_numbers__disable -\n"
        b"context:\n"
        b"  phone_hint: " + octx.phone_hint.encode("utf-8") + b"\n"
        b"computed:\n"
        b"  log_uid: " + log_uid.encode("ascii") + b"\n"
    )

    logged: Optional[bool] = None
    expected_disabled: Optional[int] = None
    expected_disabled_phones: Optional[List[str]] = None

    async def handler(step: Literal["log", "disable"], mctx: MergeContext) -> None:
        nonlocal logged, expected_disabled, expected_disabled_phones

        if step == "log":
            assert logged is None, "handler called twice for log step"
            logged = not not mctx.result.rows_affected

            if not logged:
                return

            await mctx.log.write(
                b"logged: true\n"
                b"interpretation: we logged that we intended to disable some user_phone_numbers "
                b"\ngoing to fetch details on what phone numbers we should have disabled from the log entry\n"
            )

            conn = await itgs.conn()
            cursor = conn.cursor("weak")
            resp = await _log_and_execute_query(
                cursor,
                "SELECT reason FROM merge_account_log WHERE uid=?",
                (log_uid,),
                mctx.log,
            )
            assert resp.results, resp
            assert len(resp.results) == 1, resp
            assert len(resp.results[0]) == 1, resp

            parsed_reason = json.loads(resp.results[0][0])
            assert isinstance(parsed_reason, dict), resp
            await mctx.log.write(
                b"parsed_reason:\n"
                + json.dumps(parsed_reason, indent=2).encode("utf-8")
                + b"\n"
            )

            details = parsed_reason["context"]["disabled"]
            rows = parsed_reason["context"]["rows"]

            assert isinstance(details, list), resp
            assert all(isinstance(s, str) for s in details), resp
            assert isinstance(rows, int), resp
            assert len(details) == rows, resp
            assert rows > 0

            expected_disabled = rows
            expected_disabled_phones = details
            await mctx.log.write(
                b"reason is correctly shaped for expected_disabled="
                + str(expected_disabled).encode("ascii")
                + b"\n"
            )
            return

        assert step == "disable", step
        assert logged is not None, "disable step handler called before log step"

        num_disabled = mctx.result.rows_affected or 0
        await mctx.log.write(
            b"num_disabled: " + str(num_disabled).encode("ascii") + b"\n"
        )
        if num_disabled <= 0:
            assert (
                not logged
            ), f"logged that we intended to disable some user_phone_numbers, but none were disabled"
        else:
            assert (
                logged
            ), f"disabled some user_phone_numbers, but didn't log that we intended to verify any"
            assert expected_disabled == num_disabled, (
                f"logged that we intended to disable {expected_disabled}"
                f" user_phone_numbers, but disabled {num_disabled}"
            )
            assert expected_disabled_phones is not None

            conn = await itgs.conn()
            cursor = conn.cursor()
            for disabled_phone in expected_disabled_phones:
                await mctx.log.write(
                    b"\nwriting contact method log for newly disabled phone: "
                    + disabled_phone.encode("utf-8")
                    + b"\n"
                )
                cml_uid = f"oseh_cml_{secrets.token_urlsafe(16)}"
                await mctx.log.write(
                    b"selected cml_uid: " + cml_uid.encode("ascii") + b"\n"
                )
                await _log_and_execute_query(
                    cursor,
                    f"INSERT INTO contact_method_log ("
                    " uid, user_id, channel, identifier, action, reason, created_at"
                    ") SELECT"
                    " ?, original_user.id, 'phone', ?, 'disable_notifs', ?, ? "
                    "FROM users AS original_user "
                    "WHERE original_user.sub = ?",
                    (
                        cml_uid,
                        disabled_phone,
                        json.dumps(
                            {
                                "repo": "backend",
                                "file": __name__,
                                "context": {
                                    "merge_operation_uid": octx.operation_uid,
                                },
                            }
                        ),
                        octx.merge_at,
                        octx.original_user_sub,
                    ),
                    mctx.log,
                )
            await mctx.log.write(b"\nfinished writing contact method log entries\n")
        await mctx.log.write(b"log and disable steps matched\n")

    ctes, ctes_qargs = _merging_user_and_original_user_ctes(octx)
    ctes += (
        ", query_ctx(phone) AS ("
        "SELECT"
        " user_phone_numbers.phone_number "
        "FROM user_phone_numbers, original_user "
        "WHERE"
        "  user_phone_numbers.user_id = original_user.id"
        "  AND user_phone_numbers.phone_number <> ?"
        "  AND user_phone_numbers.receives_notifications"
        ") "
    )
    ctes_qargs.append(octx.phone_hint)
    return [
        MergeQuery(
            query=(
                f"{ctes}INSERT INTO merge_account_log ("
                " uid, user_id, operation_uid, operation_order, phase, step, step_result, reason, created_at"
                ") SELECT"
                " ?, original_user.id, ?, ?, 'merging', 'move_user_phone_numbers__disable', 'xfer',"
                " json_insert("
                "  '{}'"
                "  , '$.context.disabled', (SELECT json_group_array(phone) FROM query_ctx)"
                "  , '$.context.rows', (SELECT COUNT(*) FROM query_ctx)"
                " ), ? "
                "FROM merging_user, original_user "
                "WHERE EXISTS (SELECT 1 FROM query_ctx)"
            ),
            qargs=[
                *ctes_qargs,
                log_uid,
                octx.operation_uid,
                OperationOrder.move_user_phone_numbers__disable.value,
                octx.merge_at,
            ],
            handler=partial(handler, "log"),
        ),
        MergeQuery(
            query=(
                f"{ctes}UPDATE user_phone_numbers "
                "SET receives_notifications = 0 "
                "WHERE"
                " EXISTS (SELECT 1 FROM original_user WHERE original_user.id = user_phone_numbers.user_id)"
                " AND EXISTS (SELECT 1 FROM query_ctx WHERE query_ctx.phone = user_phone_numbers.phone_number)"
            ),
            qargs=[*ctes_qargs],
            handler=partial(handler, "disable"),
        ),
    ]


async def _move_user_profile_pictures(
    itgs: Itgs, octx: _Ctx, /
) -> Sequence[MergeQuery]:
    log_uid = f"oseh_mal_{secrets.token_urlsafe(16)}"
    await octx.log.write(
        b"- move_user_profile_pictures -\n"
        b"computed:\n"
        b"  log_uid: " + log_uid.encode("ascii") + b"\n"
    )

    logged: Optional[bool] = None
    expected_moved: Optional[int] = None
    setting_latest: Optional[bool] = None
    unset_latest: Optional[bool] = None

    async def handler(
        step: Literal["log", "unset", "move"], mctx: MergeContext
    ) -> None:
        nonlocal logged, expected_moved, setting_latest, unset_latest

        if step == "log":
            assert logged is None, "handler called twice for log step"
            logged = not not mctx.result.rows_affected

            if logged:
                await mctx.log.write(
                    b"logged: true\n"
                    b"interpretation: we logged that we intended to move some user_profile_pictures\n"
                    b"going to fetch if we intended to unset the latest flag on the merging ones first\n"
                )

                conn = await itgs.conn()
                cursor = conn.cursor("weak")
                resp = await _log_and_execute_query(
                    cursor,
                    "SELECT json_extract(reason, '$.context.setting_latest'), json_extract(reason, '$.context.rows') FROM merge_account_log WHERE uid=?",
                    (log_uid,),
                    mctx.log,
                )
                assert resp.results, resp
                assert len(resp.results) == 1, resp
                assert len(resp.results[0]) == 2, resp
                setting_latest = bool(resp.results[0][0])
                expected_moved = int(resp.results[0][1])
                await mctx.log.write(
                    b"setting_latest: " + str(setting_latest).encode("ascii") + b"\n"
                    b"expected_moved: " + str(expected_moved).encode("ascii") + b"\n"
                )
            return

        if step == "unset":
            assert logged is not None, "unset called before log step"
            if logged:
                assert setting_latest is not None, "log step didn't set setting_latest"
            assert unset_latest is None, "handler called twice for unset step"

            unset_latest = not not mctx.result.rows_affected

            assert (
                logged or not unset_latest
            ), f"didnt log a move but did unset latest? {logged=} {unset_latest=}"
            if unset_latest:
                assert (
                    mctx.result.rows_affected == 1
                ), f"unset multiple latest flags? {mctx.result=}"

            if setting_latest and unset_latest:
                assert (
                    False
                ), f"copying over latest but still unset some rows? {mctx.result=}"

            await mctx.log.write(
                b"unset_latest: " + str(unset_latest).encode("ascii") + b"\n"
            )
            return

        assert step == "move", step
        assert logged is not None, "move step handler called before log step"
        assert unset_latest is not None, "move step handler called before unset step"

        num_moved = mctx.result.rows_affected or 0
        await mctx.log.write(b"num_moved: " + str(num_moved).encode("ascii") + b"\n")
        if num_moved <= 0:
            assert (
                not logged
            ), f"logged that we intended to move some user_profile_pictures, but none were moved"
        else:
            assert (
                logged
            ), f"moved some user_profile_pictures, but didn't log that we intended to move any"
            assert expected_moved == num_moved, (
                f"logged that we intended to move {expected_moved}"
                f" user_profile_pictures, but moved {num_moved}"
            )
        await mctx.log.write(b"log and move steps matched\n")

    ctes, ctes_qargs = _merging_user_and_original_user_ctes(octx)
    return [
        MergeQuery(
            query=(
                f"{ctes}, query_ctx(rows, setting_latest) AS ("
                "SELECT"
                " (SELECT COUNT(*) FROM user_profile_pictures, merging_user WHERE user_id = merging_user.id),"
                " NOT EXISTS (SELECT 1 FROM user_profile_pictures AS upp, original_user WHERE upp.user_id = original_user.id AND upp.latest)"
                ") INSERT INTO merge_account_log ("
                " uid, user_id, operation_uid, operation_order, phase, step, step_result, reason, created_at"
                ") SELECT"
                " ?, original_user.id, ?, ?, 'merging', 'move_user_profile_pictures', 'xfer',"
                " json_insert("
                "  '{}'"
                "  , '$.context.rows', query_ctx.rows"
                "  , '$.context.setting_latest', json(iif(query_ctx.setting_latest, 'true', 'false'))"
                " ), ? "
                "FROM merging_user, original_user, query_ctx "
                "WHERE query_ctx.rows > 0"
            ),
            qargs=[
                *ctes_qargs,
                log_uid,
                octx.operation_uid,
                OperationOrder.move_user_profile_pictures.value,
                octx.merge_at,
            ],
            handler=partial(handler, "log"),
        ),
        MergeQuery(
            query=(
                f"{ctes} UPDATE user_profile_pictures "
                "SET latest = 0 "
                "WHERE"
                " EXISTS (SELECT 1 FROM merging_user WHERE merging_user.id = user_profile_pictures.user_id)"
                " AND latest"
                " AND NOT EXISTS ("
                "  SELECT 1 FROM merge_account_log"
                "  WHERE"
                "   merge_account_log.uid = ?"
                "   AND json_extract(merge_account_log.reason, '$.context.setting_latest')"
                " )"
            ),
            qargs=[
                *ctes_qargs,
                log_uid,
            ],
            handler=partial(handler, "unset"),
        ),
        MergeQuery(
            query=(
                f"{ctes} UPDATE user_profile_pictures "
                "SET user_id = original_user.id "
                "FROM original_user, merging_user "
                "WHERE"
                " user_id = merging_user.id"
            ),
            qargs=[*ctes_qargs],
            handler=partial(handler, "move"),
        ),
    ]


async def _move_visitor_users(itgs: Itgs, octx: _Ctx, /) -> Sequence[MergeQuery]:
    log_uid = f"oseh_mal_{secrets.token_urlsafe(16)}"
    await octx.log.write(
        b"- move_visitor_users -\n"
        b"computed:\n"
        b"  log_uid: " + log_uid.encode("ascii") + b"\n"
    )

    logged: Optional[bool] = None
    merging_visitor_uids: Optional[List[str]] = None
    bumped: Optional[bool] = None

    async def handler(
        step: Literal["log", "bump", "delete"], mctx: MergeContext
    ) -> None:
        nonlocal logged, merging_visitor_uids, bumped

        if step == "log":
            assert logged is None, "handler called twice for log step"
            logged = not not mctx.result.rows_affected

            if not logged:
                return

            await mctx.log.write(
                b"logged: true\n"
                b"interpretation: we logged that we intended to move some visitor_users\n"
                b"the way we do this is by deleting the visitor_users within the transaction,\n"
                b"bumping the visitor version as required, then afterward we queue associating\n"
                b"the deleted visitors with the original user\n"
                b"going to fetch the visitor uids we should have deleted from the log entry\n"
            )
            conn = await itgs.conn()
            cursor = conn.cursor("weak")
            response = await _log_and_execute_query(
                cursor,
                "SELECT reason FROM merge_account_log WHERE uid=?",
                (log_uid,),
                mctx.log,
            )
            assert response.results, response
            assert len(response.results) == 1, response
            assert len(response.results[0]) == 1, response
            raw_reason = response.results[0][0]
            parsed_reason = json.loads(raw_reason)
            assert isinstance(parsed_reason, dict), response
            await mctx.log.write(
                b"parsed_reason:\n"
                + json.dumps(parsed_reason, indent=2).encode("utf-8")
                + b"\n"
            )
            merging_visitor_uids = parsed_reason["context"]["uids"]
            rows = parsed_reason["context"]["rows"]

            assert isinstance(merging_visitor_uids, list), response
            assert all(isinstance(s, str) for s in merging_visitor_uids), response
            assert isinstance(rows, int), response
            assert len(merging_visitor_uids) == rows, response
            assert rows > 0

            await mctx.log.write(
                b"reason is correctly shaped for rows="
                + str(rows).encode("ascii")
                + b", uids="
                + json.dumps(merging_visitor_uids, indent=2).encode("utf-8")
                + b"\n"
            )

            redis = await itgs.redis()
            # we purposely ignore locks and backpressure
            async with redis.pipeline() as pipe:
                pipe.multi()
                for visitor_uid in merging_visitor_uids:
                    msg = (
                        QueuedVisitorUser(
                            visitor_uid=visitor_uid,
                            user_sub=octx.original_user_sub,
                            seen_at=octx.merge_at,
                        )
                        .model_dump_json()
                        .encode("utf-8")
                    )
                    await mctx.log.write(
                        b"\nqueuing visitor user association:\n" + msg + b"\n"
                    )
                    await pipe.rpush(b"visitors:user_associations", msg)  # type: ignore
                result = await pipe.execute()  # type: ignore

            await mctx.log.write(
                b"\nfinished queuing visitor user associations\n"
                b"pipeline result: " + repr(result).encode("utf-8") + b"\n"
            )
            return

        if step == "bump":
            assert logged is not None, "bump called before log step"

            affected_rows = mctx.result.rows_affected or 0
            bumped = affected_rows > 0
            if not logged and not bumped:
                return

            await mctx.log.write(
                b"affected_rows: " + str(affected_rows).encode("ascii") + b"\n"
                b"bumped: " + str(bumped).encode("ascii") + b"\n"
            )
            assert logged and bumped, f"logged={logged} bumped={bumped}"
            assert merging_visitor_uids is not None, "log step didn't set uids"
            assert affected_rows == len(
                merging_visitor_uids
            ), f"{affected_rows=} != {len(merging_visitor_uids)=}"
            return

        assert step == "delete", step
        assert logged is not None, "delete step handler called before log step"
        assert bumped is not None, "delete step handler called before bump step"

        affected_rows = mctx.result.rows_affected or 0
        deleted = affected_rows > 0
        if not logged and not bumped and not deleted:
            return
        await mctx.log.write(
            b"affected_rows: " + str(affected_rows).encode("ascii") + b"\n"
        )
        assert (
            logged and bumped and deleted
        ), f"logged={logged} bumped={bumped} deleted={deleted}"
        assert merging_visitor_uids is not None, "log step didn't set uids"
        assert affected_rows == len(
            merging_visitor_uids
        ), f"{affected_rows=} != {len(merging_visitor_uids)=}"
        await mctx.log.write(b"log, bump, and delete steps matched\n")

    ctes, ctes_qargs = _merging_user_and_original_user_ctes(octx)
    return [
        MergeQuery(
            query=(
                f"{ctes}, query_ctx(uid) AS ("
                "SELECT visitors.uid FROM visitors, visitor_users, merging_user "
                "WHERE"
                " visitors.id = visitor_users.visitor_id"
                " AND visitor_users.user_id = merging_user.id"
                ") INSERT INTO merge_account_log ("
                " uid, user_id, operation_uid, operation_order, phase, step, step_result, reason, created_at"
                ") SELECT"
                " ?, original_user.id, ?, ?, 'merging', 'move_visitor_users', 'xfer',"
                " json_insert("
                "  '{}'"
                "  , '$.context.uids', (SELECT json_group_array(uid) FROM query_ctx)"
                "  , '$.context.rows', (SELECT COUNT(*) FROM query_ctx)"
                " ), ? "
                "FROM merging_user, original_user "
                "WHERE EXISTS (SELECT 1 FROM query_ctx)"
            ),
            qargs=[
                *ctes_qargs,
                log_uid,
                octx.operation_uid,
                OperationOrder.move_visitor_users.value,
                octx.merge_at,
            ],
            handler=partial(handler, "log"),
        ),
        MergeQuery(
            query=(
                f"{ctes} UPDATE visitors SET version=version+1 "
                "WHERE"
                " EXISTS ("
                "  SELECT 1 FROM visitor_users, merging_user"
                "  WHERE"
                "   visitor_users.visitor_id = visitors.id"
                "   AND visitor_users.user_id = merging_user.id"
                " )"
            ),
            qargs=[*ctes_qargs],
            handler=partial(handler, "bump"),
        ),
        MergeQuery(
            query=(
                f"{ctes} DELETE FROM visitor_users "
                "WHERE"
                " EXISTS ("
                "  SELECT 1 FROM merging_user"
                "  WHERE merging_user.id = visitor_users.user_id"
                " )"
            ),
            qargs=[*ctes_qargs],
            handler=partial(handler, "delete"),
        ),
    ]


async def _create_move_created_at_queries(
    itgs: Itgs, octx: _Ctx, /
) -> Sequence[MergeQuery]:
    log_uid = f"oseh_mal_{secrets.token_urlsafe(16)}"
    await octx.log.write(
        b"- move_created_at -\n"
        b"computed:\n"
        b"  log_uid: " + log_uid.encode("ascii") + b"\n"
    )

    logged: Optional[bool] = None
    merging_created_at: Optional[float] = None
    original_created_at: Optional[float] = None
    expected_assignment: Optional[bool] = None

    async def handler(step: Literal["log", "assign"], mctx: MergeContext):
        nonlocal logged, merging_created_at, original_created_at, expected_assignment

        if step == "log":
            assert logged is None, "handler called twice for log step"
            assert merging_created_at is None, "merging_created_at set before log step"
            assert (
                original_created_at is None
            ), "original_created_at set before log step"
            assert (
                expected_assignment is None
            ), "expected_assignment set before log step"

            logged = not not mctx.result.rows_affected
            if not logged and not mctx.merging_expected:
                return

            assert logged is True, "we always log this step to not lose created_at"

            conn = await itgs.conn()
            cursor = conn.cursor("weak")

            resp = await _log_and_execute_query(
                cursor,
                "SELECT json_extract(reason, '$.context') FROM merge_account_log WHERE uid=?",
                (log_uid,),
                mctx.log,
            )
            assert resp.results, resp
            assert len(resp.results) == 1, resp
            assert len(resp.results[0]) == 1, resp
            raw_context = resp.results[0][0]
            parsed_context = json.loads(raw_context)
            assert isinstance(parsed_context, dict), resp
            assert "original_created_at" in parsed_context, resp
            assert "merging_created_at" in parsed_context, resp
            assert "assignment_required" in parsed_context, resp

            merging_created_at = parsed_context["merging_created_at"]
            original_created_at = parsed_context["original_created_at"]
            expected_assignment = parsed_context["assignment_required"]

            assert isinstance(merging_created_at, (int, float)), resp
            assert isinstance(original_created_at, (int, float)), resp
            assert isinstance(expected_assignment, bool), resp
            assert expected_assignment is (
                merging_created_at < original_created_at
            ), resp

            await mctx.log.write(
                b"parsed_context:\n"
                + json.dumps(parsed_context, indent=2).encode("utf-8")
                + b"\n"
            )
            return

        assert step == "assign", step
        affected_rows = mctx.result.rows_affected or 0

        assert logged is not None, "assign step handler called before log step"
        if not logged:
            assert affected_rows == 0, f"{affected_rows=} != 0"
            return

        assert (
            merging_created_at is not None
        ), "assign step handler expected merging_created_at"
        assert (
            original_created_at is not None
        ), "assign step handler expected original_created_at"
        assert (
            expected_assignment is not None
        ), "assign step handler expected expected_assignment"

        assert affected_rows == int(
            expected_assignment
        ), f"{affected_rows=} != {expected_assignment=}"
        await mctx.log.write(
            b"affected_rows: "
            + str(affected_rows).encode("ascii")
            + b"\n"
            + b"matches expected assignment\n"
        )

        conn = await itgs.conn()
        cursor = conn.cursor("weak")
        resp = await _log_and_execute_query(
            cursor,
            "SELECT created_at FROM users WHERE sub=?",
            (octx.original_user_sub,),
            mctx.log,
        )
        assert resp.results, resp
        assert len(resp.results) == 1, resp
        assert len(resp.results[0]) == 1, resp
        created_at_after_merge = resp.results[0][0]
        assert isinstance(created_at_after_merge, (int, float)), resp
        assert (
            abs(created_at_after_merge - min(original_created_at, merging_created_at))
            < 1
        ), f"{original_created_at=}, {merging_created_at=} but {created_at_after_merge=}"
        await mctx.log.write(
            b"confirmed that created_at is now the lesser of the two\n"
        )

    ctes, ctes_qargs = _merging_user_and_original_user_ctes(
        octx, merging_user_created_at=True, original_user_created_at=True
    )
    return [
        MergeQuery(
            query=(
                f"{ctes} INSERT INTO merge_account_log ("
                " uid, user_id, operation_uid, operation_order, phase, step, step_result, reason, created_at"
                ") SELECT"
                " ?, original_user.id, ?, ?, 'merging', 'move_created_at', 'xfer',"
                " json_insert("
                "  '{}'"
                "  , '$.context.original_created_at', original_user.created_at"
                "  , '$.context.merging_created_at', merging_user.created_at"
                "  , '$.context.assignment_required', json(iif(merging_user.created_at < original_user.created_at, 'true', 'false'))"
                " ), ? "
                "FROM merging_user, original_user"
            ),
            qargs=[
                *ctes_qargs,
                log_uid,
                octx.operation_uid,
                OperationOrder.move_created_at.value,
                octx.merge_at,
            ],
            handler=partial(handler, "log"),
        ),
        MergeQuery(
            query=(
                f"{ctes} UPDATE users SET created_at=merging_user.created_at "
                "FROM merge_account_log, merging_user, original_user "
                "WHERE"
                " merge_account_log.uid = ?"
                " AND json_extract(merge_account_log.reason, '$.context.assignment_required')"
                " AND users.id = original_user.id"
            ),
            qargs=[
                *ctes_qargs,
                log_uid,
            ],
            handler=partial(handler, "assign"),
        ),
    ]


async def _delete_merging_user(itgs: Itgs, octx: _Ctx, /) -> Sequence[MergeQuery]:
    async def handler(mctx: MergeContext) -> None:
        deleted = not not mctx.result.rows_affected

        if not deleted and not mctx.merging_expected:
            return

        await mctx.log.write(b"deleted: " + str(deleted).encode("ascii") + b"\n")
        assert (
            deleted is mctx.merging_expected
        ), f"{deleted=} is not {mctx.merging_expected=}"

    ctes, ctes_qargs = _merging_user_and_original_user_ctes(octx)
    return [
        MergeQuery(
            query=(
                f"{ctes}DELETE FROM users "
                "WHERE"
                " EXISTS ("
                "  SELECT 1 FROM merging_user"
                "  WHERE merging_user.id = users.id"
                " )"
            ),
            qargs=[*ctes_qargs],
            handler=handler,
        ),
    ]


async def _create_log_move_merge_queries(
    itgs: Itgs,
    octx: _Ctx,
    /,
    *,
    table_name: str,
    operation_order: OperationOrder,
    column_name: str = "user_id",
) -> Sequence[MergeQuery]:
    """Similar to copying over a regular table, except in this case we assume
    there is a reason column that's a json object and we insert a new top-level
    key into it (named by the merging user sub for uniqueness) which contains
    the original user sub and a reference to this merge operation
    """
    log_uid = f"oseh_mal_{secrets.token_urlsafe(16)}"
    await octx.log.write(
        b"- move_" + bytes(table_name, "utf-8") + b" -\n"
        b"computed:\n"
        b"  log_uid: " + log_uid.encode("ascii") + b"\n"
    )

    handler = await _create_simple_handler(itgs, octx, table_name, log_uid=log_uid)
    log_query, log_qargs = _create_standard_log_query(
        octx,
        table_name=table_name,
        log_uid=log_uid,
        operation_order=operation_order,
    )
    ctes, ctes_qargs = _merging_user_and_original_user_ctes(octx, merging_user_sub=True)
    return [
        MergeQuery(
            query=log_query,
            qargs=log_qargs,
            handler=partial(handler, "log"),
        ),
        MergeQuery(
            query=(
                f"{ctes}UPDATE {table_name} "
                "SET"
                f" {column_name} = original_user.id,"
                " reason = json_insert("
                "  reason,"
                "  ('$._merged_' || merging_user.sub),"
                "  json_object("
                "   'original', ?"
                "   , 'operation_uid', ?"
                "   , 'merged_at', ?"
                "  )"
                " )"
                "FROM original_user, merging_user "
                f"WHERE {column_name} = merging_user.id"
            ),
            qargs=[
                *ctes_qargs,
                octx.original_user_sub,
                octx.operation_uid,
                octx.merge_at,
            ],
            handler=partial(handler, "move"),
        ),
    ]


async def _create_standard_move_merge_queries(
    itgs: Itgs,
    octx: _Ctx,
    /,
    *,
    table_name: str,
    operation_order: OperationOrder,
    column_name: str = "user_id",
    reason_extra: str = "",
    reason_extra_qargs: Sequence[Any] = tuple(),
) -> Sequence[MergeQuery]:
    log_uid = f"oseh_mal_{secrets.token_urlsafe(16)}"
    await octx.log.write(
        b"- move_" + bytes(table_name, "utf-8") + b" -\n"
        b"computed:\n"
        b"  log_uid: " + log_uid.encode("ascii") + b"\n"
    )

    handler = await _create_simple_handler(itgs, octx, table_name, log_uid=log_uid)
    log_query, log_qargs = _create_standard_log_query(
        octx,
        table_name=table_name,
        column_name=column_name,
        log_uid=log_uid,
        operation_order=operation_order,
        reason_extra=reason_extra,
        reason_extra_qargs=reason_extra_qargs,
    )
    move_query, move_qargs = _create_standard_update_query(
        octx,
        table_name=table_name,
        column_name=column_name,
    )
    return [
        MergeQuery(
            query=log_query,
            qargs=log_qargs,
            handler=partial(handler, "log"),
        ),
        MergeQuery(
            query=move_query,
            qargs=move_qargs,
            handler=partial(handler, "move"),
        ),
    ]


def _create_standard_log_query(
    octx: _Ctx,
    /,
    *,
    table_name: str,
    column_name: str = "user_id",
    log_uid: str,
    operation_order: OperationOrder,
    reason_extra: str = "",
    reason_extra_qargs: Sequence[Any] = tuple(),
) -> Tuple[str, Sequence[Any]]:
    ctes, ctes_qargs = _merging_user_and_original_user_ctes(octx)
    return (
        (
            f"{ctes}, query_ctx(rows) AS ("
            f" SELECT COUNT(*) FROM {table_name}, merging_user WHERE {table_name}.{column_name} = merging_user.id"
            ") INSERT INTO merge_account_log ("
            " uid, user_id, operation_uid, operation_order, phase, step, step_result, reason, created_at"
            ") SELECT"
            f" ?, original_user.id, ?, ?, 'merging', ?, 'xfer', json_insert('{{}}', '$.context.rows', query_ctx.rows{reason_extra}), ? "
            "FROM merging_user, original_user, query_ctx "
            "WHERE query_ctx.rows > 0"
        ),
        [
            *ctes_qargs,
            log_uid,
            octx.operation_uid,
            operation_order.value,
            f"move_{table_name}",
            *reason_extra_qargs,
            octx.merge_at,
        ],
    )


def _create_standard_update_query(
    octx: _Ctx,
    *,
    table_name: str,
    column_name: str = "user_id",
) -> Tuple[str, Sequence[Any]]:
    ctes, ctes_qargs = _merging_user_and_original_user_ctes(octx)
    return (
        f"{ctes}UPDATE {table_name} "
        f"SET {column_name} = original_user.id "
        "FROM original_user, merging_user "
        f"WHERE {table_name}.{column_name} = merging_user.id",
        ctes_qargs,
    )


def _merging_user_and_original_user_ctes(
    octx: _Ctx,
    /,
    *,
    merging_user_sub: bool = False,
    original_user_sub: bool = False,
    merging_user_created_at: bool = False,
    original_user_created_at: bool = False,
) -> Tuple[str, List[Any]]:
    merging_user_columns = "id"
    if merging_user_sub:
        merging_user_columns += ", sub"
    if merging_user_created_at:
        merging_user_columns += ", created_at"

    merging_user_select = "users.id"
    if merging_user_sub:
        merging_user_select += ", users.sub"
    if merging_user_created_at:
        merging_user_select += ", users.created_at"

    original_user_columns = "id"
    if original_user_sub:
        original_user_columns += ", sub"
    if original_user_created_at:
        original_user_columns += ", created_at"

    original_user_select = "users.id"
    if original_user_sub:
        original_user_select += ", users.sub"
    if original_user_created_at:
        original_user_select += ", users.created_at"

    return (
        f"WITH merging_user({merging_user_columns}) AS ("
        f" SELECT {merging_user_select} FROM merge_account_log, users"
        " WHERE"
        "  merge_account_log.uid = ?"
        "  AND merge_account_log.step_result = ?"
        "  AND users.sub = json_extract(merge_account_log.reason, '$.context.merging.user_sub')"
        "), "
        f"original_user({original_user_columns}) AS (SELECT {original_user_select} FROM users WHERE users.sub=? AND EXISTS (SELECT 1 FROM merging_user)) ",
        [
            octx.confirm_log_uid,
            octx.confirm_required_step_result,
            octx.original_user_sub,
        ],
    )


async def _create_simple_handler(
    itgs: Itgs, octx: _Ctx, table_name: str, /, *, log_uid: str
) -> Callable[[Literal["log", "move"], MergeContext], Awaitable[None]]:
    logged: Optional[bool] = None
    expected_moved: Optional[int] = None
    table_name_bytes = table_name.encode("ascii")

    async def handler(step: Literal["log", "move"], mctx: MergeContext) -> None:
        nonlocal logged, expected_moved

        if step == "log":
            assert logged is None, "handler called twice for log step"
            logged = not not mctx.result.rows_affected

            if logged:
                await mctx.log.write(
                    b"logged: true\n"
                    b"interpretation: we logged that we intended to move some "
                    + table_name_bytes
                    + b"\ngoing to fetch the number expected to move from the log entry\n"
                )

                conn = await itgs.conn()
                cursor = conn.cursor("weak")
                resp = await _log_and_execute_query(
                    cursor,
                    "SELECT json_extract(reason, '$.context.rows') FROM merge_account_log WHERE uid=?",
                    (log_uid,),
                    mctx.log,
                )
                assert resp.results, resp
                assert len(resp.results) == 1, resp
                assert len(resp.results[0]) == 1, resp
                expected_moved = int(resp.results[0][0])
                assert expected_moved > 0, resp

                await mctx.log.write(
                    b"expected_moved=" + str(expected_moved).encode("ascii") + b"\n"
                )
            return

        assert step == "move", step
        assert logged is not None, "move step handler called before log step"

        num_moved = mctx.result.rows_affected or 0
        await mctx.log.write(b"num_moved: " + str(num_moved).encode("ascii") + b"\n")
        if num_moved <= 0:
            assert (
                not logged
            ), f"logged that we intended to move some {table_name}, but none were moved"
        else:
            assert (
                logged
            ), f"moved some {table_name}, but didn't log that we intended to move any"
            assert expected_moved == num_moved, (
                f"logged that we intended to move {expected_moved}"
                f" {table_name}, but moved {num_moved}"
            )
        await mctx.log.write(b"log and move steps matched\n")

    return handler


async def _log_and_execute_query(
    cursor: AsyncCursor,
    query: str,
    qargs: Sequence[Any],
    log: AsyncWritableBytesIO,
    indent: bytes = b"",
) -> ResultItem:
    """Logs that we are going to execute the given query, executes it, logs the result, and returns it.
    This is in addition to the built-in logging from rqdb
    """
    await _log_query(query, qargs, log, indent=indent)
    resp = await cursor.execute(query, qargs)
    await _log_query_result(resp, log, indent=indent)
    return resp


async def _log_query(
    query: str, qargs: Sequence[Any], log: AsyncWritableBytesIO, *, indent: bytes = b""
) -> None:
    """Logs that we are going to execute the given query"""
    await log.write(
        indent + b"query: " + query.encode("utf-8") + b"\n" + indent + b"args:\n"
    )
    for i, arg in enumerate(qargs):
        await log.write(
            indent
            + b"  "
            + str(i).encode("ascii")
            + b": "
            + (
                (b"\n    " + indent).join(
                    [
                        s.encode("utf-8")
                        for s in json.dumps(arg, indent=2).splitlines(keepends=False)
                    ]
                )
            )
            + b"\n"
        )


async def _log_query_result(
    result: ResultItem, log: AsyncWritableBytesIO, *, indent: bytes = b""
) -> None:
    """Logs the result of the given query"""
    await log.write(indent + b"result:\n")
    await log.write(indent + b"  rows:")
    if result.results is not None:
        for row_idx, row in enumerate(result.results):
            await log.write(
                b"\n" + indent + b"    ROW " + str(row_idx).encode("ascii") + b":\n"
            )
            for i, col in enumerate(row):
                await log.write(
                    indent
                    + b"      "
                    + str(i).encode("ascii")
                    + b": "
                    + (
                        (b"\n        " + indent).join(
                            [
                                s.encode("utf-8")
                                for s in json.dumps(col, indent=2).splitlines(
                                    keepends=False
                                )
                            ]
                        )
                    )
                    + b"\n"
                )
    else:
        await log.write(b" null\n")
    await log.write(indent + b"  error: " + str(result.error).encode("utf-8") + b"\n")
    await log.write(
        indent
        + b"  rows affected: "
        + str(result.rows_affected).encode("ascii")
        + b"\n"
    )
