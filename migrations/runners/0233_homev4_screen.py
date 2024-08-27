import json
import secrets
from itgs import Itgs
from lib.client_flows.helper import check_oas_30_schema
from lib.client_flows.screen_flags import ClientScreenFlag
from migrations.shared.shared_screen_configurable_trigger_001 import (
    shared_screen_configurable_trigger_001,
)
from migrations.shared.shared_screen_transition_002 import (
    SHARED_SCREEN_TRANSITION_SCHEMA_V002,
)


async def up(itgs: Itgs) -> None:
    schema = {
        "type": "object",
        "example": {
            "menu": {"trigger": {"type": "flow", "flow": "simple_nav"}},
            "goal": {"trigger": {"type": "flow", "flow": "set_goal"}},
            "classes": {"trigger": {"type": "flow", "flow": "library"}},
            "favorites": {
                "trigger": {
                    "type": "flow",
                    "flow": "library",
                    "parameters": {
                        "filter": {
                            "favorites": "only",
                            "instructors": [],
                            "taken": "ignore",
                        }
                    },
                }
            },
            "checkin": {
                "trigger": {
                    "type": "flow",
                    "flow": "journal_chat",
                    "endpoint": "/api/1/users/me/screens/pop_to_new_journal_entry",
                    "parameters": {},
                },
                "text": "Check-in",
            },
        },
        "required": ["checkin"],
        "properties": {
            "entrance": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
            "menu": {
                "type": "object",
                "description": "Configures menu icon in the header",
                "example": {"trigger": {"type": "flow", "flow": "simple_nav"}},
                "default": {},
                "properties": {
                    "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
                    "trigger": shared_screen_configurable_trigger_001(
                        "If the user hits the menu icon in the header"
                    ),
                },
            },
            "goal": {
                "type": "object",
                "description": "Configures goal section",
                "example": {"trigger": {"type": "flow", "flow": "set_goal"}},
                "default": {},
                "properties": {
                    "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
                    "trigger": shared_screen_configurable_trigger_001(
                        "If the user hits the goal part of the pill"
                    ),
                },
            },
            "classes": {
                "type": "object",
                "description": "Configures classes button",
                "example": {"trigger": {"type": "flow", "flow": "library"}},
                "default": {},
                "properties": {
                    "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
                    "trigger": shared_screen_configurable_trigger_001(
                        "If the user hits the classes button in the bottom left"
                    ),
                },
            },
            "favorites": {
                "type": "object",
                "description": "Configures favorites button in the bottom",
                "example": {
                    "trigger": {
                        "type": "flow",
                        "flow": "library",
                        "parameters": {
                            "filter": {
                                "favorites": "only",
                                "instructors": [],
                                "taken": "ignore",
                            }
                        },
                    }
                },
                "default": {},
                "properties": {
                    "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
                    "trigger": shared_screen_configurable_trigger_001(
                        "If the user hits the favorites button in the bottom"
                    ),
                },
            },
            "checkin": {
                "type": "object",
                "description": "Configures check-in button in the bottom right",
                "example": {
                    "trigger": {
                        "type": "flow",
                        "flow": "journal_chat",
                        "endpoint": "/api/1/users/me/screens/pop_to_new_journal_entry",
                        "parameters": {},
                    },
                    "text": "Check-in",
                },
                "required": ["text"],
                "properties": {
                    "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
                    "trigger": shared_screen_configurable_trigger_001(
                        "If the user hits the check-in button in the bottom"
                    ),
                    "text": {
                        "type": "string",
                        "example": "Check-in",
                        "description": "The text to display on the check-in button",
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
            "homev4",
            "Home V4",
            "A simplified home screen with a full-screen background, basic navigation at the top, copy in the center, and 3 buttons at the bottom. Supported in v84 and higher",
            json.dumps(schema, sort_keys=True),
            int(
                ClientScreenFlag.SHOWS_IN_ADMIN
                | ClientScreenFlag.SHOWS_ON_BROWSER
                | ClientScreenFlag.SHOWS_ON_ANDROID
                | ClientScreenFlag.SHOWS_ON_IOS
            ),
        ),
    )
