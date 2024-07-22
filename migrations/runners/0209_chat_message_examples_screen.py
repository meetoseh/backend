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
            "header": "Write how you are feeling and we’ll curate the perfect class",
            "body": "Write how you’re feeling or share what you are doing",
            "messages": [
                "I’m feeling anxious about work and can’t seem to relax",
                "I’m feeling happy and want to cherish this moment",
                "I’m feeling a bit down and need encouragement",
                "I’m having trouble sleeping and need to calm my mind",
            ],
        },
        "required": ["header", "body", "messages"],
        "properties": {
            "entrance": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
            "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
            "header": {
                "type": "string",
                "description": "Large prominent text at the top",
                "example": "Write how you are feeling and we’ll curate the perfect class",
            },
            "body": {
                "type": "string",
                "description": "Text below the header",
                "example": "Write how you’re feeling or share what you are doing",
            },
            "messages": {
                "type": "array",
                "description": "The example messages to show",
                "example": [
                    "I’m feeling anxious about work and can’t seem to relax",
                    "I’m feeling happy and want to cherish this moment",
                    "I’m feeling a bit down and need encouragement",
                    "I’m having trouble sleeping and need to calm my mind",
                ],
                "items": {
                    "type": "string",
                    "description": "A message to show",
                    "example": "I’m feeling anxious about work and can’t seem to relax",
                },
            },
            "cta": {
                "type": "string",
                "description": "The call to action text",
                "example": "Continue",
                "default": "Continue",
            },
            "trigger": {
                "type": "string",
                "format": "flow_slug",
                "nullable": True,
                "example": None,
                "default": None,
                "description": "The flow to trigger when the call to action is pressed",
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
            "chat_message_examples",
            "Chat Message Examples",
            "An interstitial screen intended for examples of the types of messages that can be sent in chat",
            json.dumps(schema, sort_keys=True),
            int(
                ClientScreenFlag.SHOWS_IN_ADMIN
                | ClientScreenFlag.SHOWS_ON_BROWSER
                | ClientScreenFlag.SHOWS_ON_ANDROID
                | ClientScreenFlag.SHOWS_ON_IOS
            ),
        ),
    )
