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
            "top": "📃 Getting to know you",
            "title": "What is your name?",
            "save": {"text": "Continue"},
        },
        "required": ["top", "title", "save"],
        "properties": {
            "entrance": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
            "top": {
                "type": "string",
                "example": "📃 Getting to know you",
                "description": "The text at the top of the screen that provides context",
            },
            "title": {
                "type": "string",
                "example": "What is your name?",
                "description": "The wording of the question",
            },
            "message": {
                "type": "string",
                "nullable": True,
                "example": None,
                "default": None,
                "description": "The message below the title that provides context for the question",
            },
            "back": {
                "type": "object",
                "nullable": True,
                "default": None,
                "example": {
                    "trigger": "account",
                    "text": "Back",
                },
                "required": ["text"],
                "properties": {
                    "trigger": {
                        "type": "string",
                        "format": "flow_slug",
                        "nullable": True,
                        "default": None,
                        "example": "account",
                        "description": "The flow to trigger when the back button is tapped",
                    },
                    "text": {
                        "type": "string",
                        "example": "Back",
                        "description": "The text on the back button",
                    },
                    "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
                },
            },
            "save": {
                "type": "object",
                "example": {
                    "text": "Continue",
                },
                "required": ["text"],
                "properties": {
                    "trigger": {
                        "type": "string",
                        "format": "flow_slug",
                        "nullable": True,
                        "default": None,
                        "example": "account",
                        "description": "The flow to trigger when the save button is tapped",
                    },
                    "text": {
                        "type": "string",
                        "example": "Continue",
                        "description": "The text on the save button",
                    },
                    "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
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
            "set_name",
            "Set Name",
            "Allows the user to configure their name.",
            json.dumps(schema, sort_keys=True),
            int(
                ClientScreenFlag.SHOWS_IN_ADMIN
                | ClientScreenFlag.SHOWS_ON_ANDROID
                | ClientScreenFlag.SHOWS_ON_IOS
                | ClientScreenFlag.SHOWS_ON_BROWSER
            ),
        ),
    )
