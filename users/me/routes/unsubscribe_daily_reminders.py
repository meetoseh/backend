from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal, Optional
from auth import auth_any
from lib.daily_reminders.registration_stats import (
    DailyReminderRegistrationStatsPreparer,
)
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from itgs import Itgs
from loguru import logger
import unix_dates
import pytz


class UnsubscribeDailyRemindersRequest(BaseModel):
    uid: str = Field(
        description="The uid corresponding to this subscription to daily reminders"
    )


router = APIRouter()


ERROR_404_TYPE = Literal["not_found"]


@router.delete(
    "/daily_reminders",
    status_code=204,
    responses={
        **STANDARD_ERRORS_BY_CODE,
        "404": {
            "description": "The user does not have a corresponding subscription to daily reminders",
            "model": StandardErrorResponse[ERROR_404_TYPE],
        },
    },
)
async def unsubscribe_daily_reminders(
    args: UnsubscribeDailyRemindersRequest, authorization: Optional[str] = Header(None)
):
    """Removes the subscription to daily reminders with the specified uid.

    Requires authorization for the user with that subscription.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor("weak")

        response = await cursor.execute(
            """
            SELECT 
                users.email,
                user_daily_reminders.channel
            FROM user_daily_reminders 
            JOIN users ON users.id = user_daily_reminders.user_id 
            WHERE user_daily_reminders.uid = ?
            """,
            (args.uid,),
        )

        if not response.results:
            return Response(
                content=StandardErrorResponse[ERROR_404_TYPE](
                    type="not_found",
                    message="Cannot delete a subscription which does not exist",
                ).json(),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                },
                status_code=404,
            )

        user_email, channel = response.results[0]

        response = await cursor.execute(
            """
            DELETE FROM user_daily_reminders
            WHERE
                EXISTS (
                    SELECT 1 FROM users
                    WHERE users.id = user_daily_reminders.user_id
                      AND users.sub = ?
                )
                AND user_daily_reminders.uid = ?
            """,
            (
                auth_result.result.sub,
                args.uid,
            ),
        )

        if response.rows_affected != 1:
            return Response(
                content=StandardErrorResponse[ERROR_404_TYPE](
                    type="not_found",
                    message="Cannot delete a subscription which does not exist",
                ).json(),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                },
                status_code=404,
            )

        stats = DailyReminderRegistrationStatsPreparer()
        stats.incr_unsubscribed(
            unix_dates.unix_date_today(tz=pytz.timezone("America/Los_Angeles")),
            channel,
            "user",
        )
        await stats.store(itgs)

        try:
            slack = await itgs.slack()
            await slack.send_oseh_bot_message(
                f"{user_email} ({auth_result.result.sub}) unsubscribed from {channel} daily reminders"
            )
        except:
            logger.error("Failed to send unsubscribe message to Slack")

        return Response(status_code=204)
