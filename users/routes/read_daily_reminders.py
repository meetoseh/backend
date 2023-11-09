from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import List, Literal, Optional
from admin.logs.routes.read_daily_reminder_settings_log import (
    DayOfWeek,
    interpret_day_of_week_mask,
)
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE
from itgs import Itgs

router = APIRouter()


class ReadDailyRemindersResponseItem(BaseModel):
    channel: Literal["email", "sms", "push"] = Field(
        description="the channel they are reached"
    )
    days_of_week: List[DayOfWeek] = Field(
        description="the days of the week they receive notifications on this channel",
        unique_items=True,
    )
    start_time: int = Field(
        description="The earliest they receive notifications in seconds from midnight"
    )
    end_time: int = Field(
        description="The latest they receive notifications in seconds from midnight"
    )


class ReadDailyRemindersResponse(BaseModel):
    reminders: List[ReadDailyRemindersResponseItem] = Field(
        description="the daily reminders they receive"
    )


@router.get(
    "/daily_reminders",
    response_model=ReadDailyRemindersResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_daily_reminders(sub: str, authorization: Optional[str] = Header(None)):
    """Reads the daily reminders that the user with the given sub receives.

    Requires standard authorization for an admin user
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor("none")

        response = await cursor.execute(
            "SELECT"
            " channel, day_of_week_mask, start_time, end_time "
            "FROM user_daily_reminders "
            "WHERE"
            " EXISTS ("
            "  SELECT 1 FROM users"
            "  WHERE"
            "   users.id = user_daily_reminders.user_id"
            "   AND users.sub = ?"
            " )",
            (sub,),
        )

        reminders: List[ReadDailyRemindersResponseItem] = []
        for row in response.results or []:
            reminders.append(
                ReadDailyRemindersResponseItem(
                    channel=row[0],
                    days_of_week=interpret_day_of_week_mask(row[1]),
                    start_time=row[2],
                    end_time=row[3],
                )
            )

        return Response(
            content=ReadDailyRemindersResponse(reminders=reminders).json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
