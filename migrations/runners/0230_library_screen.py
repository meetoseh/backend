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
            "close": {"variant": "x"},
            "journey_trigger": {
                "type": "flow",
                "flow": "journey_my_library",
                "endpoint": "/api/1/users/me/screens/pop_to_public_class",
                "parameters": {},
            },
            "edit_filter_trigger": {"type": "flow", "flow": "library_filter"},
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
                        "The trigger to fire when the user clicks the close button"
                    ),
                    "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
                },
            },
            "tooltip": {
                "type": "object",
                "default": None,
                "nullable": True,
                "example": {
                    "header": "Library Tooltip",
                    "body": "This is some text you can use to add context for the screen",
                },
                "description": "A callout thats shown before the journeys",
                "required": ["header", "body"],
                "properties": {
                    "header": {
                        "type": "string",
                        "example": "Library Tooltip",
                        "description": "Emphasized bold text at the top of the tooltip; try to keep to one line",
                    },
                    "body": {
                        "type": "string",
                        "example": "This is some text you can use to add context for the screen",
                        "description": "De-emphasized text below the header, usually a short paragraph",
                    },
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
                        "The trigger to fire when the user clicks the CTA"
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
                "description": "The filter to apply to the library",
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
            "journey_trigger": shared_screen_configurable_trigger_001(
                "handles when a journey is clicked; we include `journey_uid` in the params"
            ),
            "edit_filter_trigger": shared_screen_configurable_trigger_001(
                "handles when the user clicks the filter button"
            ),
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
            "library",
            "Library",
            "Allows the user to view the library of journeys",
            json.dumps(schema, sort_keys=True),
            int(
                ClientScreenFlag.SHOWS_IN_ADMIN
                | ClientScreenFlag.SHOWS_ON_ANDROID
                | ClientScreenFlag.SHOWS_ON_IOS
                | ClientScreenFlag.SHOWS_ON_BROWSER
            ),
        ),
    )
