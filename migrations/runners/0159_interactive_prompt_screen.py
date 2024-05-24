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
            "prompt": "oseh_ian_placeholder",
        },
        "required": ["prompt"],
        "properties": {
            "prompt": {
                "type": "string",
                "format": "interactive_prompt_uid",
                "example": "oseh_ian_placeholder",
                "description": "The interactive prompt to display",
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
            "countdown": {
                "type": "string",
                "nullable": True,
                "default": None,
                "example": "Class Poll",
                "description": "If the remaining time in the prompt should be presented as a countdown, the title for that countdown, otherwise null",
            },
            "entrance": SHARED_SCREEN_TRANSITION_SCHEMA_V001,
            "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V001,
            "trigger": {
                "type": "string",
                "format": "flow_slug",
                "nullable": True,
                "default": None,
                "example": None,
                "description": "The flow to trigger when they finish the prompt. Triggered with no parameters",
            },
        },
    }

    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    check_oas_30_schema(schema, require_example=True)

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
            "interactive_prompt",
            "Interactive Prompt",
            "Displays an interactive prompt (like a journey lobby) with an optional fullscreen background",
            json.dumps(schema, sort_keys=True),
            int(
                ClientScreenFlag.SHOWS_IN_ADMIN
                | ClientScreenFlag.SHOWS_ON_ANDROID
                | ClientScreenFlag.SHOWS_ON_IOS
                | ClientScreenFlag.SHOWS_ON_BROWSER
            ),
        ),
    )
