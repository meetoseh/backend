import os
import secrets
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
import pytz
from lib.client_flows.executor import (
    ClientScreenQueuePeekInfo,
    TrustedTrigger,
    UntrustedTrigger,
    execute_peek,
    execute_pop,
)
from lib.daily_reminders.registration_stats import (
    DailyReminderRegistrationStatsPreparer,
)
from lib.shared.describe_user import enqueue_send_described_user_slack_message
from models import STANDARD_ERRORS_BY_CODE
from typing import Annotated, Optional
from itgs import Itgs
import auth as std_auth
import unix_dates
import users.me.screens.auth
from loguru import logger

from users.me.screens.lib.realize_screens import realize_screens
from users.me.screens.models.peeked_screen import PeekScreenResponse
from visitors.lib.get_or_create_visitor import VisitorSource


router = APIRouter()


class PopUnsubscribingEmailParameters(BaseModel):
    email: str = Field(description="The email address to unsubscribe")
    code: str = Field(
        description="The link code that was used to get to the unsubscribe screen"
    )


class PopUnsubscribingEmailTriggerRequest(BaseModel):
    slug: str = Field(description="The slug of the client flow to trigger")
    parameters: PopUnsubscribingEmailParameters = Field(
        description="The parameters to convert"
    )


class PopUnsubscribingEmailRequest(BaseModel):
    screen_jwt: str = Field(description="The JWT which lets you pop the screen")
    trigger: PopUnsubscribingEmailTriggerRequest = Field(
        description="The client flow to trigger",
    )


@router.post(
    "/pop_unsubscribing_email",
    response_model=PeekScreenResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def pop_unsubscribing_email(
    args: PopUnsubscribingEmailRequest,
    platform: VisitorSource,
    version: Optional[int] = None,
    visitor: Annotated[Optional[str], Header()] = None,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """A specialized pop endpoint which unsubscribes the given email address from
    reminders, if it was receiving reminders, and then triggers the given flow
    with `email` in the client parameters.

    Requires standard authorization for a user.
    """
    async with Itgs() as itgs:
        std_auth_result = await std_auth.auth_any(itgs, authorization)
        if std_auth_result.result is None:
            return std_auth_result.error_response

        user_sub = std_auth_result.result.sub

        async def _realize(screen: ClientScreenQueuePeekInfo):
            result = await realize_screens(
                itgs,
                user_sub=user_sub,
                platform=platform,
                visitor=visitor,
                result=screen,
            )

            return Response(
                content=result.__pydantic_serializer__.to_json(result),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=200,
            )

        screen_auth_result = await users.me.screens.auth.auth_any(
            itgs, args.screen_jwt, prefix=None
        )
        if screen_auth_result.result is None:
            screen = await execute_peek(
                itgs,
                user_sub=std_auth_result.result.sub,
                platform=platform,
                version=version,
                trigger=TrustedTrigger(
                    flow_slug="error_bad_auth",
                    client_parameters={},
                    server_parameters={},
                ),
            )
            return await _realize(screen)

        conn = await itgs.conn()
        cursor = conn.cursor()

        suppressed_emails_uid = f"oseh_se_{secrets.token_urlsafe(16)}"
        unsubscribed_emails_log_uid = f"oseh_uel_{secrets.token_urlsafe(16)}"
        unsubscribed_at = time.time()

        result = await cursor.executemany3(
            (
                (
                    """
                    INSERT INTO suppressed_emails (
                        uid, email_address, reason, created_at
                    )
                    SELECT
                        ?, ?, ?, ?
                    WHERE
                        NOT EXISTS (
                            SELECT 1 FROM suppressed_emails WHERE email_address = ? COLLATE NOCASE
                        )
                    """,
                    (
                        suppressed_emails_uid,
                        args.trigger.parameters.email,
                        "User",
                        unsubscribed_at,
                        args.trigger.parameters.email,
                    ),
                ),
                (
                    """
                    WITH batch(uid, code, visitor_uid, email_address, suppressed_emails_uid, unsubscribed_at) 
                    AS (VALUES (?, ?, ?, ?, ?, ?))
                    INSERT INTO unsubscribed_emails_log (
                        uid, link_code, visitor_id, visitor_known, email_address, suppressed, created_at
                    )
                    SELECT
                        batch.uid, 
                        batch.code, 
                        visitors.id, 
                        visitors.id IS NOT NULL, 
                        batch.email_address,
                        EXISTS (
                            SELECT 1 FROM suppressed_emails
                            WHERE suppressed_emails.uid = batch.suppressed_emails_uid
                        ),
                        batch.unsubscribed_at
                    FROM batch
                    LEFT JOIN visitors ON visitors.uid = batch.visitor_uid
                    """,
                    (
                        unsubscribed_emails_log_uid,
                        args.trigger.parameters.code,
                        visitor,
                        args.trigger.parameters.email,
                        suppressed_emails_uid,
                        unsubscribed_at,
                    ),
                ),
                (
                    """
                    DELETE FROM user_daily_reminders
                    WHERE
                        EXISTS (
                            SELECT 1 FROM user_email_addresses
                            WHERE user_email_addresses.user_id = user_daily_reminders.user_id
                              AND user_email_addresses.email = ?
                        )
                        AND user_daily_reminders.channel = ?
                    """,
                    (args.trigger.parameters.email, "email"),
                ),
            )
        )

        if result[0].rows_affected is not None and result[0].rows_affected > 0:
            logger.info(
                f"Suppressed {args.trigger.parameters.email} via request by {user_sub} using unchecked code {args.trigger.parameters.code} (user clicked unsubscribe link and entered email address)"
            )
            if os.environ["ENVIRONMENT"] != "dev":
                await enqueue_send_described_user_slack_message(
                    itgs,
                    message=f"Suppressed {args.trigger.parameters.email} via `pop_unsubscribing_email` endpoint",
                    sub=user_sub,
                    channel="oseh_bot",
                )

        if result[2].rows_affected is not None and result[2].rows_affected > 0:
            await (
                DailyReminderRegistrationStatsPreparer()
                .incr_unsubscribed(
                    unix_dates.unix_timestamp_to_unix_date(
                        unsubscribed_at, tz=pytz.timezone("America/Los_Angeles")
                    ),
                    "email",
                    "user",
                    amt=result[2].rows_affected,
                )
                .store(itgs)
            )

        screen = await execute_pop(
            itgs,
            user_sub=std_auth_result.result.sub,
            platform=platform,
            version=version,
            expected_front_uid=screen_auth_result.result.user_client_screen_uid,
            trigger=(
                UntrustedTrigger(
                    flow_slug=args.trigger.slug,
                    client_parameters={
                        "email": args.trigger.parameters.email,
                    },
                )
            ),
        )
        return await _realize(screen)
