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
            "title": "A message from Paul",
            "audio": "oseh_cf_placeholder",
            "cta": "Skip",
            "entrance": {"type": "fade", "ms": 350},
            "exit": {"type": "fade", "ms": 350},
            "trigger": None,
        },
        "required": ["title", "audio"],
        "properties": {
            "title": {
                "type": "string",
                "example": "A message from Paul",
                "description": "Title of the audio, shown in the bottom left",
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
                "example": "Skip",
                "default": "Skip",
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
            "audio_interstitial",
            "Audio Interstitial",
            "Plays some audio with an optional fullscreen background",
            json.dumps(schema, sort_keys=True),
            int(
                ClientScreenFlag.SHOWS_IN_ADMIN
                | ClientScreenFlag.SHOWS_ON_ANDROID
                | ClientScreenFlag.SHOWS_ON_IOS
                | ClientScreenFlag.SHOWS_ON_BROWSER
            ),
        ),
    )
