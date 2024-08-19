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
            "header": "My Journal",
            "close": {"variant": "x"},
            "journal_entry_trigger": {
                "type": "flow",
                "flow": "view_journal_entry",
                "endpoint": "/api/1/users/me/screens/pop_to_existing_journal_entry",
                "parameters": {},
            },
            "journal_entry_edit_trigger": {
                "type": "flow",
                "flow": "edit_journal_entry",
                "endpoint": "/api/1/users/me/screens/pop_to_existing_journal_entry",
                "parameters": {},
            },
        },
        "required": ["header", "close"],
        "properties": {
            "header": {
                "type": "string",
                "description": "The text in the header",
                "example": "My Journal",
            },
            "tooltip": {
                "type": "object",
                "default": None,
                "nullable": True,
                "example": {
                    "header": "Journal Entries List Tooltip",
                    "body": "This is some text you can use to add context for the screen",
                },
                "description": "A callout thats shown before the journal entries",
                "required": ["header", "body"],
                "properties": {
                    "header": {
                        "type": "string",
                        "example": "Journal Entries List Tooltip",
                        "description": "Emphasized bold text at the top of the tooltip; try to keep to one line",
                    },
                    "body": {
                        "type": "string",
                        "example": "This is some text you can use to add context for the screen",
                        "description": "De-emphasized text below the header, usually a short paragraph",
                    },
                },
            },
            "cta": {
                "type": "object",
                "nullable": True,
                "default": None,
                "required": ["text"],
                "example": {"text": "Done"},
                "description": "The floating CTA at the bottom, or null for no floating CTA",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The text for the floating continue button",
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
            "entrance": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
            "journal_entry_trigger": shared_screen_configurable_trigger_001(
                "handles when a journal entry is clicked; we include `journal_entry_uid` in the params"
            ),
            "journal_entry_edit_trigger": shared_screen_configurable_trigger_001(
                "handles when a journal entry's edit button is clicked; we include `journal_entry_uid` in the params"
            ),
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
            "journal_entries_list",
            "Journal Entries List",
            "Allows the user to view their journal entries.",
            json.dumps(schema, sort_keys=True),
            int(
                ClientScreenFlag.SHOWS_IN_ADMIN
                | ClientScreenFlag.SHOWS_ON_ANDROID
                | ClientScreenFlag.SHOWS_ON_IOS
                | ClientScreenFlag.SHOWS_ON_BROWSER
            ),
        ),
    )
