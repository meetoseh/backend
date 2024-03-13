import secrets
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, validator
from typing import Optional
from auth import auth_any
from models import STANDARD_ERRORS_BY_CODE
from itgs import Itgs
import pytz
import time

from users.lib.timezones import (
    TimezoneTechniqueSlug,
    convert_timezone_technique_slug_to_db,
    need_set_timezone,
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
        if auth_result.result is None:
            return auth_result.error_response

        if not await need_set_timezone(
            itgs, user_sub=auth_result.result.sub, timezone=args.timezone
        ):
            return Response(status_code=202)

        conn = await itgs.conn()
        cursor = conn.cursor()

        timezone_technique = convert_timezone_technique_slug_to_db(
            args.timezone_technique
        )
        now = time.time()
        await cursor.executemany3(
            (
                (
                    "INSERT INTO user_timezone_log ("
                    " uid, user_id, timezone, source, style, guessed, created_at"
                    ") "
                    "SELECT"
                    " ?, users.id, ?, ?, ?, ?, ? "
                    "FROM users "
                    "WHERE"
                    " users.sub = ?"
                    " AND (users.timezone IS NULL OR users.timezone <> ?)",
                    (
                        f"oseh_utzl_{secrets.token_urlsafe(16)}",
                        args.timezone,
                        "explicit",
                        timezone_technique.style,
                        timezone_technique.guessed,
                        now,
                        auth_result.result.sub,
                        args.timezone,
                    ),
                ),
                (
                    "UPDATE users SET timezone = ? WHERE sub = ?",
                    (
                        args.timezone,
                        auth_result.result.sub,
                    ),
                ),
            ),
        )

        return Response(status_code=202)
