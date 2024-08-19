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
            "cta": {"text": "Begin"},
            "close": {"variant": "x", "only_if_error": True},
        },
        "required": ["header", "journal_entry", "cta", "close"],
        "properties": {
            "entrance": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
            "header": {
                "type": "string",
                "description": "The text in the header",
                "example": "Journal",
            },
            "hint": {
                "type": "string",
                "nullable": True,
                "description": "Small text below the summary to help provide clarity",
                "example": "Use the buttons on the bottom to edit or regenerate the summary.",
                "default": None,
            },
            "journal_entry": {
                "type": "string",
                "format": "journal_entry_uid",
                "description": "The journal entry to show the summary for",
                "example": "oseh_jne_placeholder",
            },
            "cta": {
                "type": "object",
                "required": ["text"],
                "example": {"text": "Begin"},
                "description": "The primary CTA at the bottom",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The text for the primary continue button",
                        "example": "Begin",
                    },
                    "trigger": shared_screen_configurable_trigger_001(
                        "The trigger to fire when the user clicks the CTA"
                    ),
                    "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
                },
            },
            "close": {
                "type": "object",
                "required": ["variant", "only_if_error"],
                "example": {"variant": "x", "only_if_error": True},
                "description": "The close button in the header",
                "properties": {
                    "variant": {
                        "type": "string",
                        "description": "The variant of the close button",
                        "example": "x",
                        "enum": ["x", "back", "menu"],
                    },
                    "only_if_error": {
                        "type": "boolean",
                        "description": "True if the error button is only shown when there is an error, false if it is always shown",
                        "example": True,
                    },
                    "trigger": shared_screen_configurable_trigger_001(
                        "The trigger to fire when the user clicks the close button"
                    ),
                    "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
                },
            },
            "regenerate": {
                "type": "object",
                "nullable": True,
                "default": {"endpoint": "/api/1/journals/entries/regenerate_summary"},
                "example": {"endpoint": "/api/1/journals/entries/regenerate_summary"},
                "description": "If not null, adds a button to regenerate the summary below the CTA",
                "required": ["endpoint"],
                "properties": {
                    "endpoint": {
                        "type": "string",
                        "description": "The endpoint to call to regenerate the summary. Must have the same signature as /api/1/journals/entries/sync except with `entry_counter` in the request body",
                        "example": "/api/1/journals/entries/regenerate_summary",
                    }
                },
            },
            "edit": {
                "type": "object",
                "nullable": True,
                "default": {"endpoint": "/api/1/journals/entries/edit_summary"},
                "example": {"endpoint": "/api/1/journals/entries/edit_summary"},
                "description": "If not null, adds a button to edit the summary below the CTA",
                "required": ["endpoint"],
                "properties": {
                    "endpoint": {
                        "type": "string",
                        "description": "The endpoint to call to edit the summary. Must have the same signature as /api/1/journals/entries/sync except with `entry_counter` and `encrypted_summary` in the request body",
                        "example": "/api/1/journals/entries/edit_summary",
                    }
                },
            },
            "missing_summary": {
                "type": "object",
                "example": {
                    "endpoint": ["/api/1/journals/entries/ensure_summary"],
                    "max_retries": 1,
                },
                "default": {
                    "endpoint": ["/api/1/journals/entries/ensure_summary"],
                    "max_retries": 1,
                },
                "required": ["endpoint", "max_retries"],
                "description": "Controls how the client handles a summary not being in the journal entry",
                "properties": {
                    "endpoint": {
                        "type": "array",
                        "description": "the endpoint to use for each retry; if shorter than max_retries, the last value is repeated. If empty, the sync endpoint is used.",
                        "items": {
                            "type": "string",
                            "description": "The endpoint to call to refresh the entry",
                            "example": "/api/1/journals/entries/ensure_summary",
                        },
                        "example": ["/api/1/journals/entries/ensure_summary"],
                    },
                    "max_retries": {
                        "type": "integer",
                        "description": "The maximum number of retries to attempt before giving up. 0 for give up immediately.",
                        "example": 1,
                        "minimum": 0,
                    },
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
            "journal_entry_summary",
            "Journal Entry Summary",
            "Shows the title and tags on the corresponding journal entry in large text, with a cta and buttons to edit or regenerate them.",
            json.dumps(schema, sort_keys=True),
            int(
                ClientScreenFlag.SHOWS_IN_ADMIN
                | ClientScreenFlag.SHOWS_ON_ANDROID
                | ClientScreenFlag.SHOWS_ON_IOS
                | ClientScreenFlag.SHOWS_ON_BROWSER
            ),
        ),
    )
