import json
from itgs import Itgs
from lib.client_flows.helper import check_oas_30_schema
from migrations.shared.shared_screen_transition_002 import (
    SHARED_SCREEN_TRANSITION_SCHEMA_V002,
)


async def up(itgs: Itgs) -> None:
    schema = {
        "type": "object",
        "example": {},
        "properties": {
            "tooltip": {
                "type": "object",
                "default": None,
                "nullable": True,
                "example": {
                    "header": "Series List Tooltip",
                    "body": "This is some text you can use to add context for the screen",
                },
                "description": "A callout thats shown before the series cards",
                "required": ["header", "body"],
                "properties": {
                    "header": {
                        "type": "string",
                        "example": "Series List Tooltip",
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
                "default": None,
                "nullable": True,
                "example": {"text": "Return Home"},
                "description": "Adds a call to action sticky to the bottom of the screen",
                "required": ["text"],
                "properties": {
                    "text": {
                        "type": "string",
                        "example": "Return Home",
                        "description": "The text to display on the button",
                    },
                    "trigger": {
                        "type": "string",
                        "format": "flow_slug",
                        "default": None,
                        "nullable": True,
                        "example": "resetme",
                        "description": "The flow to trigger when the button is pressed",
                    },
                },
            },
            "entrance": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
            "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
            "series_trigger": {
                "type": "string",
                "format": "flow_slug",
                "default": None,
                "nullable": True,
                "example": "series_details",
                "description": (
                    "The flow to trigger when a series is selected. On success, the flow "
                    "is ultimately triggered with the server parameter `series` set to the "
                    "uid of the selected series."
                ),
            },
            "bottom": {
                "type": "object",
                "nullable": True,
                "default": None,
                "example": {"home": {}, "account": {"trigger": "account"}},
                "description": "If set and not null, adds the standard bottom bar with series highlighted",
                "required": ["home", "account"],
                "properties": {
                    "home": {
                        "type": "object",
                        "description": "Configures what happens if they tap the home button in the bottom nav",
                        "example": {"trigger": None},
                        "properties": {
                            "trigger": {
                                "type": "string",
                                "format": "flow_slug",
                                "nullable": True,
                                "example": None,
                                "default": None,
                                "description": "The flow to trigger when the home button is pressed",
                            },
                            "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
                        },
                    },
                    "account": {
                        "type": "object",
                        "description": "Configures what happens if they tap the account button in the bottom nav",
                        "example": {"trigger": "account"},
                        "properties": {
                            "trigger": {
                                "type": "string",
                                "format": "flow_slug",
                                "nullable": True,
                                "example": "account",
                                "default": None,
                                "description": "The flow to trigger when the account button is pressed",
                            },
                            "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
                        },
                    },
                },
            },
        },
    }

    check_oas_30_schema(schema, require_example=True)

    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    await cursor.execute(
        "UPDATE client_screens SET schema=? WHERE slug=?",
        (json.dumps(schema, sort_keys=True), "series_list"),
    )
