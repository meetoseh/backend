import json
from itgs import Itgs
from lib.client_flows.helper import check_oas_30_schema
from migrations.shared.shared_screen_transition_001 import (
    SHARED_SCREEN_TRANSITION_SCHEMA_V001,
)


async def up(itgs: Itgs) -> None:
    schema = {
        "type": "object",
        "example": {
            "title": "Welcome Video",
            "video": "oseh_cf_placeholder",
        },
        "required": ["title", "video"],
        "properties": {
            "title": {
                "type": "string",
                "example": "A message from Paul",
                "description": "Title of the audio, shown in the bottom left. Often via extract `title` from `server.journey`",
            },
            "subtitle": {
                "type": "string",
                "nullable": True,
                "default": None,
                "example": "Paul Javid",
                "description": "The small subtitle above the title, usually the author of the work. Often via extract `instructor.name` from `server.journey`",
            },
            "close": {
                "type": "boolean",
                "default": False,
                "example": True,
                "description": "If a close button should be shown in the top right",
            },
            "dark": {
                "type": "boolean",
                "default": True,
                "example": False,
                "description": "If checked, we assume a dark background for some styling.",
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
                "nullable": True,
                "example": "Skip",
                "default": None,
                "description": "If provided, the text for the button that skips the audio in the bottom right",
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
    cursor = conn.cursor("weak")

    await cursor.execute(
        "UPDATE client_screens SET schema=? WHERE slug=?",
        (json.dumps(schema, sort_keys=True), "video_interstitial"),
    )
