import asyncio
import secrets
from typing import Annotated, Optional
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from models import STANDARD_ERRORS_BY_CODE
from image_files.models import ImageFileRef
from image_files.auth import create_jwt as create_image_jwt
from auth import auth_any
from users.lib.home_screen_images import read_home_screen_image
from itgs import Itgs
import time

from users.lib.timezones import (
    TimezoneTechniqueSlug,
    convert_timezone_technique_slug_to_db,
    need_set_timezone,
)


router = APIRouter()


class ReadHomeImageResponse(BaseModel):
    image: ImageFileRef = Field(description="The image file to show")
    thumbhash: str = Field(
        description="The thumbhash for the image at a standard resolution"
    )


@router.get(
    "/home_image",
    response_model=ReadHomeImageResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_home_image(
    tz: str,
    tzt: TimezoneTechniqueSlug,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Reads the current home screen image for the authorized user

    tz (str): IANA timezone string for the user
    tzt (TimezoneTechniqueSlug): The technique used to determine the user's timezone
    """

    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        now = time.time()
        choice, _ = await asyncio.gather(
            read_home_screen_image(
                itgs, user_sub=auth_result.result.sub, now=now, timezone=tz
            ),
            _handle_timezone(
                itgs,
                user_sub=auth_result.result.sub,
                timezone=tz,
                timezone_technique_slug=tzt,
                now=now,
            ),
        )
        return Response(
            content=ReadHomeImageResponse.__pydantic_serializer__.to_json(
                ReadHomeImageResponse(
                    image=ImageFileRef(
                        uid=choice.image_uid,
                        jwt=await create_image_jwt(
                            itgs, image_file_uid=choice.image_uid
                        ),
                    ),
                    thumbhash=choice.thumbhash,
                )
            ),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "private, max-age=15",
            },
            status_code=200,
        )


async def _handle_timezone(
    itgs: Itgs,
    *,
    user_sub: str,
    timezone: str,
    timezone_technique_slug: TimezoneTechniqueSlug,
    now: float,
):
    if not await need_set_timezone(itgs, user_sub=user_sub, timezone=timezone):
        return

    timezone_technique = convert_timezone_technique_slug_to_db(timezone_technique_slug)

    conn = await itgs.conn()
    cursor = conn.cursor()
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
                    timezone,
                    "read_home_image",
                    timezone_technique.style,
                    timezone_technique.guessed,
                    now,
                    user_sub,
                    timezone,
                ),
            ),
            (
                "UPDATE users SET timezone = ? WHERE sub = ?",
                (
                    timezone,
                    user_sub,
                ),
            ),
        ),
    )
