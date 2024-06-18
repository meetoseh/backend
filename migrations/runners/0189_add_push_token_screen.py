import json
import secrets
from itgs import Itgs
from lib.client_flows.helper import check_oas_30_schema
from lib.client_flows.screen_flags import ClientScreenFlag
from migrations.shared.shared_screen_transition_002 import (
    SHARED_SCREEN_TRANSITION_SCHEMA_V002,
)
from migrations.shared.shared_screen_exact_dynamic_image_001 import (
    shared_screen_exact_dynamic_image_001,
)


async def up(itgs: Itgs) -> None:
    schema = {
        "type": "object",
        "example": {
            "header": "Unlock motivation with regular reminders",
            "message": "Reach your goals with personalized reminders, quotes and tips.",
            "cta": {"text": "Allow Notifications"},
            "nav": {"type": "link-button", "back": "Skip"},
        },
        "required": ["header", "nav"],
        "properties": {
            "entrance": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
            "image": {
                "type": "object",
                "nullable": True,
                "default": None,
                "example": {
                    "ios": {
                        "image": "oseh_if_utnIdo3z0V65FnFSc-Rs-g",
                        "width": 200,
                        "height": 200,
                    },
                    "other": {
                        "image": "oseh_if_utnIdo3z0V65FnFSc-Rs-g",
                        "width": 200,
                        "height": 200,
                    },
                },
                "required": ["ios", "other"],
                "properties": {
                    "ios": shared_screen_exact_dynamic_image_001(["image", "ios"]),
                    "other": shared_screen_exact_dynamic_image_001(["image", "other"]),
                },
            },
            "header": {
                "type": "string",
                "example": "Unlock motivation with regular reminders.",
                "description": "The large text",
            },
            "message": {
                "type": "string",
                "nullable": True,
                "default": None,
                "example": "Reach your goals with personalized reminders, quotes and tips.",
                "description": "The small text below the header",
            },
            "times": {
                "type": "boolean",
                "example": True,
                "default": True,
                "description": "True to allow configuring when they receive push reminders right on the screen, false not to.",
            },
            "cta": {
                "type": "object",
                "required": ["text"],
                "example": {"text": "Allow Notifications"},
                "default": {"text": "Allow Notifications"},
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The text on the call to action button",
                        "example": "Allow Notifications",
                    },
                    "success": {
                        "type": "string",
                        "format": "flow_slug",
                        "nullable": True,
                        "default": None,
                        "example": None,
                        "description": "The flow to trigger with no parameters when the user presses the CTA then accepts the native prompt",
                    },
                    "failure": {
                        "type": "string",
                        "format": "flow_slug",
                        "nullable": True,
                        "default": None,
                        "example": None,
                        "description": "The flow to trigger with no parameters when the user presses the CTA then declines the native prompt",
                    },
                    "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
                },
            },
            "back": {
                "type": "object",
                "example": {},
                "default": {},
                "properties": {
                    "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
                    "trigger": {
                        "type": "string",
                        "format": "flow_slug",
                        "nullable": True,
                        "default": None,
                        "example": None,
                        "description": "The flow to trigger with no parameters when the user presses the back button",
                    },
                },
            },
            "nav": {
                "type": "object",
                "description": "Where to put the back button, plus other optional navigational elements",
                "example": {"type": "x"},
                "x-enum-discriminator": "type",
                "oneOf": [
                    {
                        "type": "object",
                        "required": ["type", "back"],
                        "example": {"type": "link-button", "back": "Skip"},
                        "description": "Shows a link button below the CTA",
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": ["link-button"],
                                "example": "link-button",
                                "description": "Shows a link button below the CTA",
                            },
                            "back": {
                                "type": "string",
                                "description": "The text on the back button",
                                "example": "Skip",
                            },
                        },
                    },
                    {
                        "type": "object",
                        "required": ["type"],
                        "description": "Shows an x button in the upper right",
                        "example": {"type": "x"},
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": ["x"],
                                "example": "x",
                                "description": "Shows an x button in the upper right",
                            }
                        },
                    },
                    {
                        "type": "object",
                        "required": ["type"],
                        "description": "Shows a back arrow in the upper left",
                        "example": {"type": "arrow"},
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": ["arrow"],
                                "example": "arrow",
                                "description": "Shows a back arrow in the upper left",
                            }
                        },
                    },
                    {
                        "type": "object",
                        "required": ["type", "title", "home", "series"],
                        "description": "Shows the standard header and bottom bar",
                        "example": {
                            "type": "header-and-footer",
                            "title": "Add Push Notifications",
                            "home": {},
                            "series": {},
                        },
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": ["header-and-footer"],
                                "example": "header-and-footer",
                                "description": "Shows the standard header and bottom bar",
                            },
                            "title": {
                                "type": "string",
                                "description": "The title of the screen",
                                "example": "Add Push Notifications",
                            },
                            "home": {
                                "type": "object",
                                "description": "Configures the home button in the bottom nav",
                                "example": {},
                                "properties": {
                                    "trigger": {
                                        "type": "string",
                                        "format": "flow_slug",
                                        "nullable": True,
                                        "default": None,
                                        "example": None,
                                        "description": "The flow to trigger with no parameters when the user presses the home button",
                                    }
                                },
                            },
                            "series": {
                                "type": "object",
                                "description": "Configures the series button in the bottom nav",
                                "example": {},
                                "properties": {
                                    "trigger": {
                                        "type": "string",
                                        "format": "flow_slug",
                                        "nullable": True,
                                        "default": None,
                                        "example": None,
                                        "description": "The flow to trigger with no parameters when the user presses the series button",
                                    }
                                },
                            },
                        },
                    },
                ],
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
            "add_push_token",
            "Add Push Token",
            "Allows the user to receive push tokens on their device. Only shows inside the native app",
            json.dumps(schema, sort_keys=True),
            int(
                ClientScreenFlag.SHOWS_IN_ADMIN
                | ClientScreenFlag.SHOWS_ON_ANDROID
                | ClientScreenFlag.SHOWS_ON_IOS
            ),
        ),
    )
