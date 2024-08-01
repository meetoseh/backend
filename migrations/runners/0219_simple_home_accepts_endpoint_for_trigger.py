from itgs import Itgs
from lib.client_flows.helper import check_oas_30_schema
from lib.client_flows.screen_cache import purge_client_screen_cache
from migrations.shared.shared_screen_transition_002 import (
    SHARED_SCREEN_TRANSITION_SCHEMA_V002,
)
import json


async def up(itgs: Itgs) -> None:
    schema = {
        "type": "object",
        "example": {
            "settings": {"trigger": "simple_nav"},
            "goal": {"trigger": "set_goal"},
            "favorites": {"trigger": "favorites"},
            "cta": {
                "text": "Start Your Practice",
                "trigger": "journal_chat",
                "endpoint": "/api/1/users/me/screens/pop_to_new_journal_entry",
            },
        },
        "properties": {
            "settings": {
                "type": "object",
                "example": {"trigger": "simple_nav"},
                "default": {},
                "description": "Handles if the user clicks on the menu button in the top left",
                "properties": {
                    "trigger": {
                        "type": "string",
                        "format": "flow_slug",
                        "nullable": True,
                        "default": None,
                        "example": "simple_nav",
                        "description": "The client flow to trigger with no parameters when the settings button is pressed",
                    },
                    "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
                },
            },
            "goal": {
                "type": "object",
                "example": {"trigger": "set_goal"},
                "default": {},
                "description": "Handles if the user clicks on their goal in the goal pill",
                "properties": {
                    "trigger": {
                        "type": "string",
                        "format": "flow_slug",
                        "nullable": True,
                        "default": None,
                        "example": "set_goal",
                        "description": "The client flow to trigger with no parameters when the goal within the goal pill is pressed",
                    },
                    "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
                },
            },
            "favorites": {
                "type": "object",
                "example": {"trigger": "favorites"},
                "default": {},
                "description": "Handles if the user clicks on the favorites shortcut in the top right",
                "properties": {
                    "trigger": {
                        "type": "string",
                        "format": "flow_slug",
                        "nullable": True,
                        "default": None,
                        "example": "favorites",
                        "description": "The client flow to trigger with no parameters when the favorites shortcut is pressed",
                    },
                    "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
                },
            },
            "cta": {
                "type": "object",
                "example": {
                    "text": "Start Your Practice",
                    "trigger": "journal_chat",
                    "endpoint": "/api/1/users/me/screens/pop_to_new_journal_entry",
                },
                "default": {
                    "text": "Start Your Practice",
                },
                "description": "Describes the primary call to action",
                "required": ["text"],
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The text for the primary call to action",
                        "example": "Start Your Practice",
                    },
                    "trigger": {
                        "type": "string",
                        "format": "flow_slug",
                        "nullable": True,
                        "default": None,
                        "example": "journal_chat",
                        "description": "The client flow to trigger with no parameters when the primary call to action is pressed",
                    },
                    "endpoint": {
                        "type": "string",
                        "nullable": True,
                        "default": None,
                        "example": "/api/1/users/me/screens/pop_to_new_journal_entry",
                        "description": "The endpoint to use for the trigger, or null for the default. Supported in version 74 and higher",
                    },
                    "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
                },
            },
            "cta2": {
                "type": "object",
                "nullable": True,
                "default": None,
                "example": None,
                "required": ["text"],
                "description": "Describes the secondary call to action (default: no second call to action)",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The text for the secondary call to action",
                        "example": "Give Feedback",
                    },
                    "trigger": {
                        "type": "string",
                        "format": "flow_slug",
                        "nullable": True,
                        "default": None,
                        "example": None,
                        "description": "The client flow to trigger with no parameters when the secondary call to action is pressed",
                    },
                    "endpoint": {
                        "type": "string",
                        "nullable": True,
                        "default": None,
                        "example": "/api/1/users/me/screens/pop_to_new_journal_entry",
                        "description": "The endpoint to use for the trigger, or null for the default. Supported in version 74 and higher",
                    },
                    "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
                },
            },
            "entrance": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
        },
    }

    check_oas_30_schema(schema, require_example=True)

    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    await cursor.execute(
        """
UPDATE client_screens SET schema=? WHERE slug=?
        """,
        (
            json.dumps(schema, sort_keys=True),
            "simple_home",
        ),
    )

    await purge_client_screen_cache(itgs, slug="simple_home")
