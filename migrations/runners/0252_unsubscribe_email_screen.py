import json
import secrets
from itgs import Itgs
from lib.client_flows.helper import check_oas_30_schema
from lib.client_flows.screen_cache import purge_client_screen_cache
from lib.client_flows.screen_flags import ClientScreenFlag
from migrations.shared.shared_screen_configurable_trigger_001 import (
    shared_screen_configurable_trigger_001,
)
from migrations.shared.shared_screen_transition_003 import (
    SHARED_SCREEN_TRANSITION_SCHEMA_V003,
)


async def up(itgs: Itgs) -> None:
    schema = {
        "type": "object",
        "example": {
            "header": "Unsubscribe",
            "title": "Enter your email address",
            "body": "The given email address will be immediately unsubscribed",
            "code": "abc123",
            "placeholder": "Email address",
            "cta": {
                "text": "Unsubscribe",
                "trigger": {
                    "type": "flow",
                    "flow": "unsubscribed_email",
                    "endpoint": "/api/1/users/me/screens/pop_unsubscribing_email",
                    "parameters": {},
                },
            },
        },
        "required": ["header", "placeholder", "cta"],
        "properties": {
            "entrance": SHARED_SCREEN_TRANSITION_SCHEMA_V003,
            "header": {
                "type": "string",
                "example": "Unsubscribe",
                "description": "The large header text at the top",
            },
            "close": {
                "type": "object",
                "example": {"variant": "x"},
                "default": {"variant": "x"},
                "required": ["variant"],
                "properties": {
                    "variant": {
                        "type": "string",
                        "example": "x",
                        "description": "The variant of the close button to use",
                        "enum": ["x", "back", "menu"],
                    },
                    "trigger": shared_screen_configurable_trigger_001(
                        "For the close button"
                    ),
                    "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V003,
                },
            },
            "title": {
                "type": "string",
                "nullable": True,
                "default": None,
                "example": "Enter your email address",
                "description": "The title text above the input or null for no title text",
            },
            "body": {
                "type": "string",
                "nullable": True,
                "default": None,
                "example": "The given email address will be immediately unsubscribed",
                "description": "The message below the title or null for no body text",
            },
            "code": {
                "type": "string",
                "nullable": True,
                "default": None,
                "example": "abc123",
                "description": "The touch link code used to get here, null will skip the screen",
            },
            "placeholder": {
                "type": "string",
                "example": "Email address",
                "description": "The placeholder text for the input",
            },
            "help": {
                "type": "string",
                "nullable": True,
                "default": None,
                "example": "We will never share your email address",
                "description": "The help text below the input or null for no help text",
            },
            "cta": {
                "type": "object",
                "example": {
                    "text": "Unsubscribe",
                    "trigger": {
                        "type": "flow",
                        "flow": "unsubscribed_email",
                        "endpoint": "/api/1/users/me/screens/pop_unsubscribing_email",
                        "parameters": {},
                    },
                },
                "required": ["text"],
                "properties": {
                    "text": {
                        "type": "string",
                        "example": "Unsubscribe",
                        "description": "The text on the call to action button",
                    },
                    "trigger": shared_screen_configurable_trigger_001(
                        "The flow to trigger with the call to action is pressed. Includes `email` and `code` in client parameters"
                    ),
                    "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V003,
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
            "unsubscribe_email",
            "Unsubscribe Email",
            "For web>=v90, allows the user to enter an email address to unsubscribe from reminders. Generally shown from "
            "touch_link_unsubscribe instead of the fast logged out unsubscribe flow now that silent auth is enabled and "
            "users are never logged out but also unlikely to have the right email address on their Oseh user. Skips if the "
            "touch link code is no longer available",
            json.dumps(schema, sort_keys=True),
            int(ClientScreenFlag.SHOWS_IN_ADMIN | ClientScreenFlag.SHOWS_ON_BROWSER),
        ),
    )

    await purge_client_screen_cache(itgs, slug="unsubscribe_email")
