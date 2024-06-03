import json
from itgs import Itgs
from lib.client_flows.helper import check_oas_30_schema
from lib.client_flows.screen_cache import purge_client_screen_cache
from migrations.shared.shared_screen_transition_002 import (
    SHARED_SCREEN_TRANSITION_SCHEMA_V002,
)


async def up(itgs: Itgs) -> None:
    schema = {
        "type": "object",
        "example": {
            "top": "📃 Getting to know you",
            "title": "How many days would you like to practice each week?",
            "message": "We’ll keep you motivated along the way.",
            "save": {"text": "Set Goal"},
        },
        "required": ["top", "title", "message", "save"],
        "properties": {
            "entrance": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
            "top": {
                "type": "string",
                "example": "📃 Getting to know you",
                "description": "The text at the top of the screen that provides context",
            },
            "title": {
                "type": "string",
                "example": "How many days would you like to practice each week?",
                "description": "The wording of the question",
            },
            "message": {
                "type": "string",
                "example": "We’ll keep you motivated along the way.",
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
                    "text": "Set Goal",
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
                        "example": "Set Goal",
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
UPDATE client_screens SET schema=? WHERE slug=?
        """,
        (
            json.dumps(schema, sort_keys=True),
            "set_goal",
        ),
    )

    await purge_client_screen_cache(itgs, slug="set_goal")
