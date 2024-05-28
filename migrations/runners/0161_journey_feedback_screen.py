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
            "journey": "oseh_j_fAnW7BvVhd0dPbd30snv8A",
        },
        "required": ["journey"],
        "properties": {
            "journey": {
                "type": "string",
                "format": "journey_uid",
                "example": "oseh_j_fAnW7BvVhd0dPbd30snv8A",
                "description": "The journey they are giving feedback on",
            },
            "entrance": SHARED_SCREEN_TRANSITION_SCHEMA_V001,
            "cta1": {
                "type": "object",
                "default": {"text": "Continue"},
                "example": {"text": "Continue"},
                "required": ["text"],
                "properties": {
                    "text": {
                        "type": "string",
                        "example": "Continue",
                        "description": "The text for the primary continue button",
                    },
                    "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V001,
                    "trigger": {
                        "type": "string",
                        "format": "flow_slug",
                        "nullable": True,
                        "example": None,
                        "default": None,
                        "description": "The client flow trigger, if any, when the first call to action is pressed",
                    },
                },
            },
            "cta2": {
                "type": "object",
                "nullable": True,
                "default": None,
                "example": None,
                "required": ["text"],
                "properties": {
                    "text": {
                        "type": "string",
                        "example": "Continue",
                        "description": "The text for the secondary continue button",
                    },
                    "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V001,
                    "trigger": {
                        "type": "string",
                        "format": "flow_slug",
                        "nullable": True,
                        "example": None,
                        "default": None,
                        "description": "The client flow trigger, if any, when the second call to action is pressed",
                    },
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
            "journey_feedback",
            "Journey Feedback",
            "Allows the user to give feedback on a journey",
            json.dumps(schema, sort_keys=True),
            int(
                ClientScreenFlag.SHOWS_IN_ADMIN
                | ClientScreenFlag.SHOWS_ON_ANDROID
                | ClientScreenFlag.SHOWS_ON_IOS
                | ClientScreenFlag.SHOWS_ON_BROWSER
            ),
        ),
    )
