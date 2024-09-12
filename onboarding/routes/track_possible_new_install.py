from fastapi import APIRouter
from itgs import Itgs

from visitors.lib.get_or_create_visitor import VisitorSource
import os
from loguru import logger

router = APIRouter()


@router.post("/track_possible_new_install", status_code=202)
async def track_possible_new_install(
    platform: VisitorSource,
    version: int,
) -> None:
    """Used to help detect sideloading or crashes before the user is able to signin."""
    if os.environ["ENVIRONMENT"] != "production":
        logger.info(f"Possible new install detected for {platform} version {version}")
        return

    async with Itgs() as itgs:
        slack = await itgs.slack()
        await slack.send_oseh_bot_message(
            f"An {platform} device, running v{version}, appears to have reached the login screen for the "
            + "first time (after the release of v88)"
        )
