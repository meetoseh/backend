import json
import secrets
from itgs import Itgs
from lib.client_flows.helper import check_oas_30_schema
from lib.client_flows.screen_flags import ClientScreenFlag
from migrations.shared.shared_screen_transition_002 import (
    SHARED_SCREEN_TRANSITION_SCHEMA_V002,
)


async def up(itgs: Itgs) -> None:
    schema = {
        "type": "object",
        "example": {
            "title": "Welcome Video",
        },
        "required": ["title"],
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
            "cta": {
                "type": "string",
                "nullable": True,
                "example": "Skip",
                "default": None,
                "description": "If provided, the text for the button that skips the audio in the bottom right",
            },
            "entrance": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
            "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
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
            "video_interstitial_onboarding",
            "Video Interstitial_onboarding",
            "The same video interstitial component from video_interstitial, but the video is selected according to Onboarding Videos",
            json.dumps(schema, sort_keys=True),
            int(
                ClientScreenFlag.SHOWS_IN_ADMIN
                | ClientScreenFlag.SHOWS_ON_ANDROID
                | ClientScreenFlag.SHOWS_ON_IOS
                | ClientScreenFlag.SHOWS_ON_BROWSER
            ),
        ),
    )
