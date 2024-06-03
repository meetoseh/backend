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
            "header": "Enter Verification Code",
            "message": "We’ve sent a text message with a 6-digit verification code.",
            "verification": {
                "uid": "oseh_pv_placeholder",
                "expires_at": 4102473600.218,
            },
            "cta": {"text": "Continue"},
            "back": {"text": "Back", "trigger": "account"},
        },
        "required": ["header", "message", "verification", "cta", "back"],
        "properties": {
            "entrance": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
            "header": {
                "type": "string",
                "example": "Enter Verification Code",
                "description": "The large header text at the top",
            },
            "message": {
                "type": "string",
                "example": "We’ve sent a text message with a 6-digit verification code.",
                "description": "The message below the header. Supports **bold** text",
            },
            "verification": {
                "type": "object",
                "example": {"uid": "oseh_pv_placeholder", "expires_at": 4102473600.218},
                "required": ["uid", "expires_at"],
                "description": "The verification that this screen is finishing, generally from the server parameters",
                "properties": {
                    "uid": {
                        "type": "string",
                        "example": "oseh_pv_placeholder",
                        "description": "The unique identifier of this verification",
                    },
                    "expires_at": {
                        "type": "number",
                        "example": 4102473600.218,
                        "description": "The time when this verification expires in seconds since the epoch",
                    },
                },
            },
            "cta": {
                "type": "object",
                "required": ["text"],
                "example": {"text": "Continue"},
                "description": "Configures the call to action button at the bottom",
                "properties": {
                    "text": {
                        "type": "string",
                        "example": "Continue",
                        "description": "The text on the call to action button",
                    },
                    "trigger": {
                        "type": "string",
                        "nullable": True,
                        "format": "flow_slug",
                        "example": "account",
                        "default": None,
                        "description": "The flow to trigger when the call to action button is tapped",
                    },
                    "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
                },
            },
            "back": {
                "type": "object",
                "example": {"text": "Back", "trigger": "account"},
                "description": "Configures the back button",
                "required": ["text"],
                "properties": {
                    "text": {
                        "type": "string",
                        "example": "Back",
                        "description": "The text on the back button",
                    },
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
            "verify_phone",
            "Verify Phone",
            "Allows the user to verify a phone number which has already been sent a 6-digit code",
            json.dumps(schema, sort_keys=True),
            int(
                ClientScreenFlag.SHOWS_IN_ADMIN
                | ClientScreenFlag.SHOWS_ON_ANDROID
                | ClientScreenFlag.SHOWS_ON_IOS
                | ClientScreenFlag.SHOWS_ON_BROWSER
            ),
        ),
    )
