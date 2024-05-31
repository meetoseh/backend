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
            "header": "When would you like [channel] reminders?",
            "message": "You can choose the days and the time that you'd like us to send you reminders.",
            "back": {
                "trigger": "account",
                "draft": {
                    "type": "confirm",
                    "title": "Save Changes?",
                    "message": "Do you want to save your changes to [channel] reminders?",
                    "save": "Yes",
                    "discard": "No",
                },
            },
            "cta": {
                "next": "Next Channel",
                "final": "Continue",
            },
            "nav": {
                "type": "nav",
                "title": "Reminder Times",
                "home": {"trigger": None},
                "series": {"trigger": "view_series_list"},
            },
        },
        "required": ["header", "message", "back", "cta", "nav"],
        "properties": {
            "entrance": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
            "channels": {
                "type": "array",
                "default": ["push", "sms", "email"],
                "example": ["push", "sms", "email"],
                "description": "The channels to let the user edit. Channels they won't be able to receive notifications for anyway (e.g., sms if they have no phone attached) will still be omitted, and the screen will be skipped if that means there are no channels to edit.",
                "items": {
                    "type": "string",
                    "enum": ["push", "sms", "email"],
                    "example": "push",
                },
            },
            "header": {
                "type": "string",
                "example": "When would you like [channel] reminders?",
                "description": "The header message. Can use [channel] for the channel they have selected (client-side).",
            },
            "message": {
                "type": "string",
                "example": "You can choose the days and the time that you'd like us to send you reminders.",
                "description": "The message below the header. Can use [channel] for the channel they have selected (client-side).",
            },
            "back": {
                "type": "object",
                "required": ["draft"],
                "example": {
                    "trigger": "account",
                    "draft": {
                        "type": "confirm",
                        "title": "Save Changes?",
                        "message": "Do you want to save your changes to [channel] reminders?",
                        "save": "Yes",
                        "discard": "No",
                    },
                },
                "description": "Configures the back button in the upper left",
                "properties": {
                    "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
                    "trigger": {
                        "type": "string",
                        "format": "flow_slug",
                        "description": "The flow slug to trigger when the back button is pressed",
                        "example": "account",
                        "nullable": True,
                        "default": None,
                    },
                    "draft": {
                        "type": "object",
                        "description": "What to do if they have unsaved changes when they hit the back button",
                        "example": {
                            "type": "confirm",
                            "title": "Save Changes?",
                            "message": "Do you want to save your changes to [channel] reminders?",
                            "save": "Yes",
                            "discard": "No",
                        },
                        "x-enum-discriminator": "type",
                        "oneOf": [
                            {
                                "type": "object",
                                "example": {"type": "save"},
                                "description": "Save the changes without asking",
                                "required": ["type"],
                                "properties": {
                                    "type": {
                                        "type": "string",
                                        "enum": ["save"],
                                        "example": "save",
                                    },
                                },
                            },
                            {
                                "type": "object",
                                "example": {"type": "discard"},
                                "description": "Discard the changes without asking",
                                "required": ["type"],
                                "properties": {
                                    "type": {
                                        "type": "string",
                                        "enum": ["discard"],
                                        "example": "discard",
                                    },
                                },
                            },
                            {
                                "type": "object",
                                "example": {
                                    "type": "confirm",
                                    "title": "Save Changes?",
                                    "message": "Do you want to save your changes to [channel] reminders?",
                                    "save": "Yes",
                                    "discard": "No",
                                },
                                "description": "Ask the user if they want to save changes",
                                "required": [
                                    "type",
                                    "title",
                                    "message",
                                    "save",
                                    "discard",
                                ],
                                "properties": {
                                    "type": {
                                        "type": "string",
                                        "enum": ["confirm"],
                                        "example": "confirm",
                                    },
                                    "title": {
                                        "type": "string",
                                        "example": "Save Changes?",
                                        "description": "The title of the popup. Can use [channel] for the channel.",
                                    },
                                    "message": {
                                        "type": "string",
                                        "example": "Do you want to save your changes to [channel] reminders?",
                                        "description": "The body of the popup. Can use [channel] for the channel.",
                                    },
                                    "save": {
                                        "type": "string",
                                        "example": "Yes",
                                        "description": "The text on the button that causes us to save the changes; emphasized. Can use [channel] for the channel.",
                                    },
                                    "discard": {
                                        "type": "string",
                                        "example": "No",
                                        "description": "The text on the button that causes us to discard the changes; deemphasized. Can use [channel] for the channel.",
                                    },
                                },
                            },
                        ],
                    },
                },
            },
            "cta": {
                "type": "object",
                "description": "Configures the call-to-action button at the bottom",
                "required": ["next", "final"],
                "example": {
                    "next": "Next Channel",
                    "final": "Continue",
                },
                "properties": {
                    "next": {
                        "type": "string",
                        "nullable": True,
                        "example": "Next Channel",
                        "description": (
                            "Null if the user has to tap on the channels at the top to switch between channels. "
                            "Otherwise, if we know the user hasn't viewed one of the channels, then we swap the "
                            "CTA to this copy and tapping it will go onto the first channel they haven't viewed."
                        ),
                    },
                    "final": {
                        "type": "string",
                        "example": "Continue",
                        "description": "The text on the button when tapping it pops the screen",
                    },
                    "trigger": {
                        "type": "string",
                        "format": "flow_slug",
                        "nullable": True,
                        "description": "The flow trigger when the final button is tapped",
                        "example": "account",
                        "default": None,
                    },
                    "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
                },
            },
            "nav": {
                "type": "object",
                "description": "Configures the navigation controls at the top and bottom",
                "x-enum-discriminator": "type",
                "example": {
                    "type": "nav",
                    "title": "Reminder Times",
                    "home": {"trigger": None},
                    "series": {"trigger": "view_series_list"},
                },
                "oneOf": [
                    {
                        "type": "object",
                        "description": "No bottom nav, very simple back button at the top left",
                        "required": ["type"],
                        "example": {"type": "no-nav"},
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": ["no-nav"],
                                "example": "no-nav",
                            },
                        },
                    },
                    {
                        "type": "object",
                        "description": "Settings-style top and bottom navigation",
                        "required": ["type", "title", "home", "series"],
                        "example": {
                            "type": "nav",
                            "title": "Reminder Times",
                            "home": {"trigger": None},
                            "series": {"trigger": "view_series_list"},
                        },
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": ["nav"],
                                "example": "nav",
                            },
                            "title": {
                                "type": "string",
                                "example": "Reminder Times",
                                "description": "The title of the screen, shown at the top",
                            },
                            "home": {
                                "type": "object",
                                "example": {},
                                "description": "Configures the Home button in the bottom nav",
                                "properties": {
                                    "trigger": {
                                        "type": "string",
                                        "format": "flow_slug",
                                        "nullable": True,
                                        "default": None,
                                        "description": "The flow to trigger when the Home button is pressed",
                                        "example": None,
                                    }
                                },
                            },
                            "series": {
                                "type": "object",
                                "example": {"trigger": "view_series_list"},
                                "description": "Configures the Series button in the bottom nav",
                                "properties": {
                                    "trigger": {
                                        "type": "string",
                                        "format": "flow_slug",
                                        "nullable": True,
                                        "default": None,
                                        "description": "The flow to trigger when the Series button is pressed",
                                        "example": None,
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
            "reminder_times",
            "Reminder Times",
            "Allows the user to configure what days and time they receive reminders on various channels",
            json.dumps(schema, sort_keys=True),
            int(
                ClientScreenFlag.SHOWS_IN_ADMIN
                | ClientScreenFlag.SHOWS_ON_ANDROID
                | ClientScreenFlag.SHOWS_ON_IOS
                | ClientScreenFlag.SHOWS_ON_BROWSER
            ),
        ),
    )
