import json
import secrets
from itgs import Itgs
from lib.client_flows.helper import check_oas_30_schema
from lib.client_flows.screen_flags import ClientScreenFlag
from migrations.shared.shared_screen_configurable_trigger_001 import (
    shared_screen_configurable_trigger_001,
)
from migrations.shared.shared_screen_transition_002 import (
    SHARED_SCREEN_TRANSITION_SCHEMA_V002,
)


async def up(itgs: Itgs) -> None:
    schema = {
        "type": "object",
        "example": {
            "header": "Journal",
            "journal_entry": "oseh_jne_placeholder",
            "cta": {"text": "Done"},
            "close": {"variant": "x"},
        },
        "required": ["header", "journal_entry", "cta", "close"],
        "properties": {
            "entrance": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
            "header": {
                "type": "string",
                "description": "The text in the header",
                "example": "Journal",
            },
            "journal_entry": {
                "type": "string",
                "format": "journal_entry_uid",
                "description": "The journal entry they are responding to",
                "example": "oseh_jne_placeholder",
            },
            "cta": {
                "type": "object",
                "required": ["text"],
                "example": {"text": "Done"},
                "description": "The primary CTA at the bottom",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The text for the primary continue button",
                        "example": "Done",
                    },
                    "trigger": shared_screen_configurable_trigger_001(
                        "The trigger to fire when the user clicks the CTA"
                    ),
                    "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
                },
            },
            "close": {
                "type": "object",
                "required": ["variant"],
                "example": {"variant": "x"},
                "description": "The close button in the header",
                "properties": {
                    "variant": {
                        "type": "string",
                        "description": "The variant of the close button",
                        "example": "x",
                        "enum": ["x", "back", "menu"],
                    },
                    "trigger": shared_screen_configurable_trigger_001(
                        "The trigger to fire when the user clicks the close button"
                    ),
                    "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
                },
            },
            "add": {
                "type": "object",
                "default": {"endpoint": "/api/1/journals/entries/reflection/"},
                "example": {"endpoint": "/api/1/journals/entries/reflection/"},
                "description": "How to handle when the user wants to add a reflection response to the entry",
                "required": ["endpoint"],
                "properties": {
                    "endpoint": {
                        "type": "string",
                        "description": "The endpoint to call to add the reflection response. Must have the same signature as /api/1/journals/entries/sync except with `encrypted_reflection_response` in the request body",
                        "example": "/api/1/journals/entries/reflection/",
                    }
                },
            },
            "edit": {
                "type": "object",
                "default": {
                    "endpoint": "/api/1/journals/entries/edit_reflection_response"
                },
                "example": {
                    "endpoint": "/api/1/journals/entries/edit_reflection_response"
                },
                "description": "How to handle when the user wants to edit a reflection response in the entry",
                "required": ["endpoint"],
                "properties": {
                    "endpoint": {
                        "type": "string",
                        "description": "The endpoint to call to edit the reflection response. Must have the same signature as /api/1/journals/entries/sync except with `entry_counter` and `encrypted_reflection_response` in the request body",
                        "example": "/api/1/journals/entries/edit_reflection_response",
                    }
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
            "journal_reflection_response",
            "Journal Reflection Response",
            "Allows the user to add or edit a reflection response within a specific journal entry. A reflection question must have already been generated; the client will not retry.",
            json.dumps(schema, sort_keys=True),
            int(
                ClientScreenFlag.SHOWS_IN_ADMIN
                | ClientScreenFlag.SHOWS_ON_ANDROID
                | ClientScreenFlag.SHOWS_ON_IOS
                | ClientScreenFlag.SHOWS_ON_BROWSER
            ),
        ),
    )
