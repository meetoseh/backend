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
            "title": "A message",
            "subtitle": "Paul Javid",
            "audio": "oseh_cf_placeholder",
            "cta": "Skip",
        },
        "required": ["title", "audio"],
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
            "audio": {
                "type": "string",
                "format": "content_uid",
                "example": "oseh_cf_placeholder",
                "x-processor": {
                    "job": "runners.screens.audio_interstitial_process_audio",
                    "list": "audio_interstitial",
                },
                "x-preview": {"type": "audio"},
                "description": "The audio to play",
            },
            "background": {
                "type": "string",
                "format": "image_uid",
                "nullable": True,
                "example": None,
                "default": None,
                "description": "The fullscreen background image, or None for the grid dark gray gradient. Requires 2560 width x 2745 height",
                "x-processor": {
                    "job": "runners.screens.process_fullscreen_background_image",
                    "list": "fullscreen_background",
                },
                "x-thumbhash": {"width": 270, "height": 470},
                "x-preview": {"width": 270, "height": 470},
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
                "description": "The client flow trigger, if any, when the audio finishes or the cta is pressed",
            },
        },
    }

    check_oas_30_schema(schema, require_example=True)

    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    await cursor.execute(
        "UPDATE client_screens SET schema=? WHERE slug=?",
        (json.dumps(schema, sort_keys=True), "audio_interstitial"),
    )
