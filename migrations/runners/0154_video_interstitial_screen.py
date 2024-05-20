import json
import secrets
from itgs import Itgs
from lib.client_flows.helper import check_oas_30_schema
from lib.client_flows.screen_flags import ClientScreenFlag
from migrations.shared.shared_screen_transition_001 import (
    SHARED_SCREEN_TRANSITION_SCHEMA_V001,
)


async def up(itgs: Itgs) -> None:
    schema = {
        "type": "object",
        "example": {
            "title": "Welcome Video",
            "video": "oseh_cf_placeholder",
            "cta": "Skip",
            "entrance": {"type": "fade", "ms": 350},
            "exit": {"type": "fade", "ms": 350},
            "trigger": None,
        },
        "required": ["title", "video"],
        "properties": {
            "title": {
                "type": "string",
                "example": "Welcome video",
                "description": "Title of the video, shown in the bottom left",
            },
            "video": {
                "type": "string",
                "format": "content_uid",
                "example": "oseh_cf_placeholder",
                "x-processor": {
                    "job": "runners.screens.video_interstitial_process_video",
                    "list": "video_interstitial",
                },
                "x-thumbhash": {"width": 187, "height": 317},
                "x-preview": {"type": "video", "width": 187, "height": 317},
                "description": "Full height video; minimum 1920x1080, though taller is preferred (e.g., 1920x3414)",
            },
            "cta": {
                "type": "string",
                "example": "Skip",
                "default": "Skip",
                "description": "If provided, the text for the button that skips the video in the bottom right",
            },
            "entrance": SHARED_SCREEN_TRANSITION_SCHEMA_V001,
            "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V001,
            "trigger": {
                "type": "string",
                "format": "flow_slug",
                "nullable": True,
                "example": None,
                "default": None,
                "description": "The client flow trigger, if any, when the video finishes or the cta is pressed",
            },
        },
    }

    check_oas_30_schema(schema, require_example=True)

    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.execute(
        """
INSERT INTO client_screens (
    uid, slug, name, description, schema, flags
)
SELECT
    ?, ?, ?, ?, ?, ?
        """,
        (
            f"oseh_cs_{secrets.token_urlsafe(16)}",
            "video_interstitial",
            "Video Interstitial",
            "A basic full screen video interstitial with an optional skip button",
            json.dumps(schema, sort_keys=True),
            int(
                ClientScreenFlag.SHOWS_IN_ADMIN
                | ClientScreenFlag.SHOWS_ON_ANDROID
                | ClientScreenFlag.SHOWS_ON_IOS
                | ClientScreenFlag.SHOWS_ON_BROWSER
            ),
        ),
    )
