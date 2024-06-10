import json
from itgs import Itgs
from lib.client_flows.helper import check_oas_30_schema
from migrations.shared.shared_screen_transition_002 import (
    SHARED_SCREEN_TRANSITION_SCHEMA_V002,
)


async def up(itgs: Itgs) -> None:
    legal_example = """
By continuing you agree to our [Terms] and [Privacy Policy], and to receive
marketing messages from Oseh. Msg & data rates may apply. Approx. 1 message
per day. Consent is not a condition of signup. Text HELP for help or STOP to
cancel.
    """.strip()

    schema = {
        "type": "object",
        "example": {
            "header": "Unlock motivation with regular practice",
            "message": "Reach your goal with personalized reminders, quotes and tips.",
            "reminders": True,
            "legal": legal_example,
            "cta": {"text": "Verify Phone", "trigger": "verify_phone"},
            "back": {"trigger": "account"},
            "nav": {
                "type": "nav",
                "title": "Add Phone",
                "home": {"trigger": None},
                "series": {"trigger": "view_series_list"},
            },
        },
        "required": ["header", "message", "reminders", "cta", "nav"],
        "properties": {
            "entrance": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
            "header": {
                "type": "string",
                "example": "Unlock motivation with regular practice",
                "description": "The large header text below the platform sensitive icon",
            },
            "message": {
                "type": "string",
                "example": "Reach your goal with personalized reminders, quotes and tips.",
                "description": "The message below the header that provides additional context",
            },
            "reminders": {
                "type": "boolean",
                "example": True,
                "description": "Whether or not the phone they are adding will receive SMS reminders",
            },
            "legal": {
                "type": "string",
                "nullable": True,
                "default": None,
                "example": legal_example,
                "description": "The legal text at the bottom of the screen. Client-side, [Terms] is replaced with the link to the terms of service, and [Privacy Policy] is replaced with the link to the privacy policy",
            },
            "cta": {
                "type": "object",
                "required": ["text"],
                "example": {
                    "text": "Verify Phone",
                    "trigger": "verify_phone",
                },
                "properties": {
                    "text": {
                        "type": "string",
                        "example": "Verify Phone",
                        "description": "The text on the call to action button",
                    },
                    "trigger": {
                        "type": "string",
                        "nullable": True,
                        "format": "flow_slug",
                        "example": "verify_phone",
                        "default": None,
                        "description": (
                            "The flow to trigger when the call to action button is tapped. "
                            "In the server parameters, provided `phone_number` and `verification`, "
                            "where `phone_number` is an E.164 formatted number, `verification.uid` "
                            "can be used for checking the code they were sent, and `verification.expires_at` "
                            "is when the code we sent is no longer useful in seconds since the unix epoch."
                        ),
                    },
                    "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
                },
            },
            "back": {
                "type": "object",
                "nullable": True,
                "example": {"trigger": "account"},
                "default": {
                    "trigger": None,
                    "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002["default"],
                },
                "properties": {
                    "trigger": {
                        "type": "string",
                        "nullable": True,
                        "format": "flow_slug",
                        "example": "account",
                        "default": None,
                        "description": "The flow to trigger when the back button is tapped",
                    },
                    "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
                },
            },
            "nav": {
                "type": "object",
                "example": {
                    "type": "nav",
                    "title": "Add Phone",
                    "home": {"trigger": None},
                    "series": {"trigger": "view_series_list"},
                },
                "x-enum-discriminator": "type",
                "oneOf": [
                    {
                        "type": "object",
                        "example": {"type": "no-nav", "back": "Skip"},
                        "required": ["type", "back"],
                        "properties": {
                            "type": {
                                "type": "string",
                                "example": "no-nav",
                                "enum": ["no-nav"],
                                "description": "No top or bottom bar; a text button (usually 'Skip') is shown below the CTA and above the legal text.",
                            },
                            "back": {
                                "type": "string",
                                "example": "Skip",
                                "description": "The text on the back button",
                            },
                        },
                    },
                    {
                        "type": "object",
                        "example": {
                            "type": "nav",
                            "title": "Add Phone",
                            "home": {"trigger": None},
                            "series": {"trigger": "view_series_list"},
                        },
                        "required": ["type", "title", "home", "series"],
                        "properties": {
                            "type": {
                                "type": "string",
                                "example": "nav",
                                "enum": ["nav"],
                                "description": "A top bar with a back button and title, plus the bottom bar with account highlighted",
                            },
                            "title": {
                                "type": "string",
                                "example": "Add Phone",
                                "description": "The title of the screen in the top bar",
                            },
                            "home": {
                                "type": "object",
                                "example": {"trigger": None},
                                "description": "Configures the home button in the bottom nav",
                                "properties": {
                                    "trigger": {
                                        "type": "string",
                                        "nullable": True,
                                        "format": "flow_slug",
                                        "example": None,
                                        "default": None,
                                        "description": "The flow to trigger when the home button is tapped, with no parameters",
                                    }
                                },
                            },
                            "series": {
                                "type": "object",
                                "example": {"trigger": "view_series_list"},
                                "description": "Configures the series button in the bottom nav",
                                "properties": {
                                    "trigger": {
                                        "type": "string",
                                        "nullable": True,
                                        "format": "flow_slug",
                                        "example": "view_series_list",
                                        "default": None,
                                        "description": "The flow to trigger when the series button is tapped, with no parameters",
                                    }
                                },
                            },
                        },
                    },
                ],
            },
        },
    }

    check_oas_30_schema(schema, require_example=True)

    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    await cursor.execute(
        "UPDATE client_screens SET schema=? WHERE slug=?",
        (json.dumps(schema, sort_keys=True), "add_phone"),
    )
