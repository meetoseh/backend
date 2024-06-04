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
            "slug": "age",
            "top": "📝 Getting to know you",
            "header": "How old are you?",
            "message": "Age helps us tailor your mindfulness experience for you.",
            "choices": [
                "18-24",
                "25-34",
                "35-44",
                "45-54",
                "55-64",
                "65+",
            ],
            "multiple": False,
            "enforce": False,
            "cta": "Continue",
        },
        "required": ["top", "slug", "header", "choices", "multiple", "enforce", "cta"],
        "properties": {
            "entrance": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
            "slug": {
                "type": "string",
                "example": "age",
                "description": "An identifier for this question. Good slug choices makes for easier analytics",
                "pattern": "^[a-z0-9_]+$",
                "minLength": 1,
            },
            "top": {
                "type": "string",
                "example": "📝 Getting to know you",
                "description": "The message at the top of the screen, generally providing overall context",
            },
            "header": {
                "type": "string",
                "example": "How old are you?",
                "description": "The large header text / the wording of the question",
            },
            "message": {
                "type": "string",
                "nullable": True,
                "default": None,
                "example": "Age helps us tailor your mindfulness experience for you.",
                "description": "The message below the header.",
            },
            "choices": {
                "type": "array",
                "example": [
                    "18-24",
                    "25-34",
                    "35-44",
                    "45-54",
                    "55-64",
                    "65+",
                ],
                "items": {
                    "type": "string",
                    "example": "18-24",
                },
                "minItems": 1,
                "description": "The choices the user can select from",
            },
            "multiple": {
                "type": "boolean",
                "example": False,
                "description": "Whether the user can select multiple choices",
            },
            "enforce": {
                "type": "boolean",
                "example": False,
                "description": "Whether the user must select at least one choice",
            },
            "cta": {
                "type": "string",
                "example": "Continue",
                "description": "The text on the call to action button",
            },
            "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
            "trigger": {
                "type": "string",
                "nullable": True,
                "default": None,
                "example": "account",
                "description": "The trigger to fire when the user completes this screen, with no parameters.",
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
            "choices",
            "Choices",
            "Allows the user to select from a list of choices",
            json.dumps(schema, sort_keys=True),
            int(
                ClientScreenFlag.SHOWS_IN_ADMIN
                | ClientScreenFlag.SHOWS_ON_ANDROID
                | ClientScreenFlag.SHOWS_ON_IOS
                | ClientScreenFlag.SHOWS_ON_BROWSER
            ),
        ),
    )
