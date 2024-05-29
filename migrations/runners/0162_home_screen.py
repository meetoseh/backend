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
            "emotion": {"trigger": "emotion_class"},
            "series": {"trigger": "view_series_list"},
            "account": {"trigger": "account"},
            "goal": {"trigger": "set_goal"},
        },
        "required": ["emotion", "series", "account", "goal"],
        "properties": {
            "entrance": SHARED_SCREEN_TRANSITION_SCHEMA_V001,
            "emotion": {
                "type": "object",
                "required": ["trigger"],
                "example": {"trigger": "emotion_class"},
                "properties": {
                    "trigger": {
                        "type": "string",
                        "format": "flow_slug",
                        "example": "emotion_class",
                        "description": "Triggered with emotion in the client parameters when they tap an emotion",
                    },
                    "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V001,
                },
            },
            "series": {
                "type": "object",
                "required": ["trigger"],
                "example": {"trigger": "view_series_list"},
                "properties": {
                    "trigger": {
                        "type": "string",
                        "format": "flow_slug",
                        "example": "view_series_list",
                        "description": "Triggered with no parameters if they tap Series in the bottom nav",
                    },
                    "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V001,
                },
            },
            "account": {
                "type": "object",
                "required": ["trigger"],
                "example": {"trigger": "account"},
                "properties": {
                    "trigger": {
                        "type": "string",
                        "format": "flow_slug",
                        "example": "account",
                        "description": "Triggered with no parameters if they tap Account in the bottom nav",
                    },
                    "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V001,
                },
            },
            "goal": {
                "type": "object",
                "required": ["trigger"],
                "example": {"trigger": "set_goal"},
                "properties": {
                    "trigger": {
                        "type": "string",
                        "format": "flow_slug",
                        "example": "set_goal",
                        "description": "Triggered with no parameters if they tap on their goal on the goal pill",
                    },
                    "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V001,
                },
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
            "home",
            "Home",
            "The home screen with the home image and copy at the top, emotions in the middle, and which has the bottom nav",
            json.dumps(schema, sort_keys=True),
            int(
                ClientScreenFlag.SHOWS_IN_ADMIN
                | ClientScreenFlag.SHOWS_ON_ANDROID
                | ClientScreenFlag.SHOWS_ON_IOS
                | ClientScreenFlag.SHOWS_ON_BROWSER
            ),
        ),
    )
