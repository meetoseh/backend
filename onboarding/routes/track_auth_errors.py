from fastapi import APIRouter
from fastapi.responses import Response
from typing import Annotated
from pydantic import BaseModel, Field, StringConstraints
from itgs import Itgs

from visitors.lib.get_or_create_visitor import VisitorSource
import os
from loguru import logger
import socket

router = APIRouter()


class TrackAuthErrorsRequest(BaseModel):
    category: Annotated[str, StringConstraints(max_length=255)] = Field(
        description="A short description of the error"
    )
    extra: Annotated[str, StringConstraints(max_length=1023)] = Field(
        description="Any extra information that may be useful for debugging"
    )


@router.post("/track_auth_errors", status_code=202)
async def track_possible_new_install(
    platform: VisitorSource, version: int, args: TrackAuthErrorsRequest
):
    """Used for a client to report issues with authorization, which obviously
    cannot be authenticated
    """
    if os.environ["ENVIRONMENT"] != "production":
        logger.info(
            f"Tracking auth error for {platform} version {version}: {args.category=}, {args.extra=}"
        )
    else:
        async with Itgs() as itgs:
            slack = await itgs.slack()
            await slack.send_oseh_bot_message(
                f"{socket.gethostname()} - client reported authorization error: `{args.category=}`, `{args.extra=}`"
            )

    # it's convenient for the frontend to return json
    return Response(
        content=b"{}",
        headers={"Content-Type": "application/json; charset=utf-8"},
        status_code=202,
    )
