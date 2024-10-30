import json
import secrets
from itgs import Itgs
from lib.client_flows.helper import check_oas_30_schema
from lib.client_flows.screen_cache import purge_client_screen_cache
from lib.client_flows.screen_flags import ClientScreenFlag
from migrations.shared.shared_screen_configurable_trigger_001 import (
    shared_screen_configurable_trigger_001,
)
from migrations.shared.shared_screen_text_content_001 import (
    SHARED_SCREEN_TEXT_CONTENT_SCHEMA_V001,
)
from migrations.shared.shared_screen_transition_003 import (
    SHARED_SCREEN_TRANSITION_SCHEMA_V003,
)


async def up(itgs: Itgs) -> None:
    schema = {
        "type": "object",
        "example": {
            "top": "💭 Your perfect class",
            "content": {
                "type": "screen-text-content",
                "version": 1,
                "parts": [
                    {"type": "header", "value": "Let’s find your perfect class"},
                    {"type": "spacer", "pixels": 16},
                    {
                        "type": "body",
                        "value": "Skip the browsing. Just share how you’re feeling and Oseh will curate the perfect class just for you.",
                    },
                    {"type": "spacer", "pixels": 32},
                    {"type": "check", "message": "We will never sell your data"},
                    {"type": "spacer", "pixels": 8},
                    {
                        "type": "check",
                        "message": "You can delete your data any any time",
                    },
                    {"type": "spacer", "pixels": 8},
                    {
                        "type": "check",
                        "message": "Your data is encrypted in transit and at rest",
                    },
                ],
            },
            "primary_button": {"text": "I’m ready"},
        },
        "required": ["content"],
        "properties": {
            "entrance": SHARED_SCREEN_TRANSITION_SCHEMA_V003,
            "top": {
                "type": "string",
                "nullable": True,
                "default": None,
                "example": "💭 Your perfect class",
                "description": "The text at the top of the screen, usually to provide context",
            },
            "content": SHARED_SCREEN_TEXT_CONTENT_SCHEMA_V001,
            "primary_button": {
                "type": "object",
                "nullable": True,
                "default": None,
                "example": {"text": "Continue"},
                "required": ["text"],
                "properties": {
                    "text": {
                        "type": "string",
                        "example": "Continue",
                        "description": "The text of the primary call to action (filled white button)",
                    },
                    "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V003,
                    "trigger": shared_screen_configurable_trigger_001(
                        "How to handle the primary button being pressed"
                    ),
                },
            },
            "secondary_button": {
                "type": "object",
                "nullable": True,
                "default": None,
                "example": {"text": "Continue"},
                "required": ["text"],
                "properties": {
                    "text": {
                        "type": "string",
                        "example": "Continue",
                        "description": "The text of the secondary call to action (outlined white button)",
                    },
                    "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V003,
                    "trigger": shared_screen_configurable_trigger_001(
                        "How to handle the secondary button being pressed"
                    ),
                },
            },
            "tertiary_button": {
                "type": "object",
                "nullable": True,
                "default": None,
                "example": {"text": "Continue"},
                "required": ["text"],
                "properties": {
                    "text": {
                        "type": "string",
                        "example": "Continue",
                        "description": "The text of the tertiary call to action (link button)",
                    },
                    "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V003,
                    "trigger": shared_screen_configurable_trigger_001(
                        "How to handle the tertiary button being pressed"
                    ),
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
            "text_interstitial",
            "Text Interstitial",
            "For v>=v96, a text interstitial screen with highly configurable content",
            json.dumps(schema, sort_keys=True),
            int(
                ClientScreenFlag.SHOWS_IN_ADMIN
                | ClientScreenFlag.SHOWS_ON_BROWSER
                | ClientScreenFlag.SHOWS_ON_IOS
                | ClientScreenFlag.SHOWS_ON_ANDROID
            ),
        ),
    )

    await purge_client_screen_cache(itgs, slug="text_interstitial")
