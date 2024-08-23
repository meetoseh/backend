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
            "header": "Classes",
            "close": {
                "variant": "x",
                "trigger": {"type": "flow", "flow": "library", "parameters": {}},
            },
            "cta": {
                "text": "Done",
                "trigger": {"type": "flow", "flow": "library", "parameters": {}},
            },
        },
        "required": ["header", "close"],
        "properties": {
            "entrance": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
            "header": {
                "type": "string",
                "description": "The text in the header",
                "example": "Classes",
            },
            "close": {
                "type": "object",
                "required": ["variant"],
                "example": {"variant": "x"},
                "description": "The close button in the header",
                "properties": {
                    "variant": {
                        "type": "string",
                        "description": "The variant of the close button",
                        "example": "x",
                        "enum": ["x", "back", "menu"],
                    },
                    "trigger": shared_screen_configurable_trigger_001(
                        "The trigger to fire when the user clicks the close button. Includes `filter` in the params"
                    ),
                    "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
                },
            },
            "cta": {
                "type": "object",
                "nullable": True,
                "default": None,
                "required": ["text"],
                "example": {"text": "Done"},
                "description": "The floating CTA at the bottom, or null for no floating CTA",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The text for the floating continue button",
                        "example": "Done",
                    },
                    "trigger": shared_screen_configurable_trigger_001(
                        "The trigger to fire when the user clicks the CTA. Includes `filter` in the params"
                    ),
                    "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
                },
            },
            "filter": {
                "type": "object",
                "default": {
                    "favorites": "ignore",
                    "taken": "ignore",
                    "instructors": [],
                },
                "description": "The initial filter value to prefill",
                "required": ["favorites", "taken"],
                "example": {
                    "favorites": "ignore",
                    "taken": "ignore",
                    "instructors": [],
                },
                "properties": {
                    "favorites": {
                        "type": "string",
                        "description": "The favorite filter to apply",
                        "example": "ignore",
                        "enum": ["ignore", "only", "exclude"],
                    },
                    "taken": {
                        "type": "string",
                        "description": "The taken filter to apply",
                        "example": "ignore",
                        "enum": ["ignore", "only", "exclude"],
                    },
                    "instructors": {
                        "type": "array",
                        "description": "The instructors that are included in the result; empty for all instructors",
                        "example": [],
                        "default": [],
                        "items": {
                            "type": "string",
                            "description": "The instructor uid",
                            "example": "oseh_i_placeholder",
                        },
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
            "library_filter",
            "Library Filter",
            "Allows the user to edit a filter for the Library screen, usually returning to the library screen.",
            json.dumps(schema, sort_keys=True),
            int(
                ClientScreenFlag.SHOWS_IN_ADMIN
                | ClientScreenFlag.SHOWS_ON_ANDROID
                | ClientScreenFlag.SHOWS_ON_IOS
                | ClientScreenFlag.SHOWS_ON_BROWSER
            ),
        ),
    )
