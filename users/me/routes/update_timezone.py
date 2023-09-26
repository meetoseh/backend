import json
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, validator
from typing import Literal, Optional
from auth import auth_any
from models import STANDARD_ERRORS_BY_CODE
from itgs import Itgs
import pytz

from users.lib.timezones import (
    TimezoneTechniqueSlug,
    convert_timezone_technique_slug_to_db,
)


router = APIRouter()


class UpdateTimezoneArgs(BaseModel):
    timezone: str = Field(description="the new timezone")
    timezone_technique: TimezoneTechniqueSlug = Field(
        description="The technique used to determine the timezone."
    )

    @validator("timezone")
    def validate_timezone(cls, v):
        if v not in pytz.all_timezones:
            raise ValueError("Must be an IANA timezone, e.g. America/New_York")
        return v


@router.post(
    "/attributes/timezone",
    status_code=202,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def update_timezone(
    args: UpdateTimezoneArgs, authorization: Optional[str] = Header(None)
):
    """Updates the authorized users timezone. We only store timezones for notifications,
    so this may do nothing. This process is asynchronous.

    Requires standard authorization.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor()

        timezone_technique = convert_timezone_technique_slug_to_db(
            args.timezone_technique
        )

        await cursor.executemany3(
            (
                (
                    "UPDATE users SET timezone = ?, timezone_technique = ? WHERE sub = ?",
                    (
                        args.timezone,
                        timezone_technique,
                        auth_result.result.sub,
                    ),
                ),
                (
                    """
                    UPDATE user_notification_settings
                    SET
                        timezone = ?,
                        timezone_technique = ?
                    WHERE
                        EXISTS (
                            SELECT 1 FROM users
                            WHERE users.id = user_notification_settings.user_id
                                AND users.sub = ?
                        )
                    """,
                    (
                        args.timezone,
                        timezone_technique,
                        auth_result.result.sub,
                    ),
                ),
            ),
        )

        jobs = await itgs.jobs()
        await jobs.enqueue(
            "runners.klaviyo.ensure_user",
            user_sub=auth_result.result.sub,
            timezone=args.timezone,
            timezone_technique=args.timezone_technique,
        )
        return Response(status_code=202)
