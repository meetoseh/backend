import json
import secrets
from itgs import Itgs
from lib.client_flows.helper import check_oas_30_schema
from lib.client_flows.screen_flags import ClientScreenFlag
from migrations.shared.shared_screen_transition_002 import (
    SHARED_SCREEN_TRANSITION_SCHEMA_V002,
)


async def up(itgs: Itgs) -> None:
    simple_nav_items_schema = [
        {
            "type": "object",
            "description": "Triggers a flow when tapped",
            "example": {"type": "trigger", "text": "Favorites", "trigger": "favorites"},
            "required": ["type", "text"],
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["trigger"],
                    "example": "trigger",
                    "description": "Triggers a flow when tapped",
                },
                "text": {
                    "type": "string",
                    "example": "Favorites",
                    "description": "The text to display",
                },
                "trigger": {
                    "type": "string",
                    "format": "flow_slug",
                    "nullable": True,
                    "example": None,
                    "default": None,
                    "description": "The flow to trigger when tapped",
                },
            },
        },
        {
            "type": "object",
            "description": "Opens a link when tapped",
            "example": {
                "type": "link",
                "text": "Privacy Policy",
                "url": "https://www.oseh.com/privacy",
            },
            "required": ["type", "text", "url"],
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["link"],
                    "example": "link",
                    "description": "Opens a link when tapped",
                },
                "text": {
                    "type": "string",
                    "example": "Privacy Policy",
                    "description": "The text to display",
                },
                "url": {
                    "type": "string",
                    "example": "https://www.oseh.com/privacy",
                    "description": "The link to open when tapped",
                },
            },
        },
    ]

    schema = {
        "type": "object",
        "example": {
            "primary": [
                {"type": "trigger", "text": "Favorites", "trigger": "favorites"},
                {"type": "trigger", "text": "History", "trigger": "history"},
                {"type": "trigger", "text": "Series", "trigger": "view_series_list"},
            ],
            "secondary": [
                {"type": "trigger", "text": "Settings", "trigger": "account"},
                {
                    "type": "link",
                    "text": "Privacy Policy",
                    "url": "https://www.oseh.com/privacy",
                },
                {
                    "type": "link",
                    "text": "Terms & Conditions",
                    "url": "https://www.oseh.com/terms",
                },
            ],
        },
        "required": ["primary", "secondary"],
        "properties": {
            "entrance": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
            "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
            "close": {
                "type": "string",
                "format": "flow_slug",
                "nullable": True,
                "example": None,
                "default": None,
                "description": "The flow to trigger if the close button is tapped",
            },
            "primary": {
                "type": "array",
                "example": [
                    {"type": "trigger", "text": "Favorites", "trigger": "favorites"},
                    {"type": "trigger", "text": "History", "trigger": "history"},
                    {
                        "type": "trigger",
                        "text": "series",
                        "trigger": "view_series_list",
                    },
                ],
                "description": "The items in the primary section (the bigger links)",
                "items": {
                    "type": "object",
                    "example": {
                        "type": "trigger",
                        "text": "Favorites",
                        "trigger": "favorites",
                    },
                    "description": "An item within the primary section (a big link)",
                    "x-enum-discriminator": "type",
                    "oneOf": simple_nav_items_schema,
                },
            },
            "secondary": {
                "type": "array",
                "example": [
                    {"type": "trigger", "text": "Settings", "trigger": "account"},
                    {
                        "type": "link",
                        "text": "Privacy Policy",
                        "url": "https://www.oseh.com/privacy",
                    },
                    {
                        "type": "link",
                        "text": "Terms & Conditions",
                        "url": "https://www.oseh.com/terms",
                    },
                ],
                "description": "The items in the secondary section (the smaller links)",
                "items": {
                    "type": "object",
                    "example": {
                        "type": "trigger",
                        "text": "Settings",
                        "trigger": "account",
                    },
                    "description": "An item within the secondary section (a smaller link)",
                    "x-enum-discriminator": "type",
                    "oneOf": simple_nav_items_schema,
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
            "simple_nav",
            "Simple Nav",
            "A simple navigation screen with a close button in the upper right",
            json.dumps(schema, sort_keys=True),
            int(
                ClientScreenFlag.SHOWS_IN_ADMIN
                | ClientScreenFlag.SHOWS_ON_BROWSER
                | ClientScreenFlag.SHOWS_ON_ANDROID
                | ClientScreenFlag.SHOWS_ON_IOS
            ),
        ),
    )
