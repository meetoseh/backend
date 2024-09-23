import json
import os
from itgs import Itgs
from lib.client_flows.helper import check_oas_30_schema
from lib.client_flows.screen_cache import purge_client_screen_cache
from migrations.shared.shared_screen_configurable_trigger_001 import (
    shared_screen_configurable_trigger_001,
)
from migrations.shared.shared_screen_transition_003 import (
    SHARED_SCREEN_TRANSITION_SCHEMA_V003,
)


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.execute(
        """
CREATE TABLE passkey_accounts (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    client_id TEXT UNIQUE NOT NULL,
    credential TEXT NOT NULL,
    created_at REAL NOT NULL
)
        """
    )

    schema = {
        "type": "object",
        "example": {
            "header": "Welcome back.",
            "message": "It looks like you have created an account with us before. Please try logging in with one of the suggestions below.",
            "providers": [],
            "skip": {
                "text": "Ignore duplicate account",
            },
        },
        "required": ["header", "providers", "skip"],
        "properties": {
            "entrance": SHARED_SCREEN_TRANSITION_SCHEMA_V003,
            "header": {
                "type": "string",
                "example": "Welcome back.",
                "description": "The large header text at the top",
            },
            "message": {
                "type": "string",
                "nullable": True,
                "default": None,
                "example": "It looks like you have created an account with us before. Please try logging in with one of the suggestions below.",
                "description": "The message below the header.",
            },
            "providers": {
                "type": "array",
                "example": [],
                "description": "The providers to suggest. If empty, the screen is skipped. Use $.standard.merge.suggest to fill this value for the automatic suggestions",
                "items": {
                    "type": "object",
                    "required": ["provider", "url"],
                    "example": {
                        "provider": "Google",
                        "url": os.environ["ROOT_FRONTEND_URL"] + "#example",
                    },
                    "properties": {
                        "provider": {
                            "type": "string",
                            "enum": [
                                "SignInWithApple",
                                "Google",
                                "Direct",
                                "Passkey",
                                "Dev",
                            ],
                            "example": "Google",
                            "description": "Which provider to suggest.",
                        },
                        "url": {
                            "type": "string",
                            "example": os.environ["ROOT_FRONTEND_URL"] + "#example",
                            "description": "The URL to redirect the user to when they click the button. Generally, this comes from {standard[merge][url][PROVIDER_NAME]}",
                        },
                    },
                },
            },
            "skip": {
                "type": "object",
                "description": "The button to skip the merge process. The trigger is also called if there are no suggestions.",
                "example": {
                    "text": "Ignore duplicate account",
                },
                "required": ["text"],
                "properties": {
                    "text": {
                        "type": "string",
                        "example": "Ignore duplicate account",
                        "description": "The text on the call to action button",
                    },
                    "trigger": {
                        "type": "string",
                        "format": "flow_slug",
                        "nullable": True,
                        "default": None,
                        "deprecated": True,
                        "example": "account",
                        "description": "The flow to trigger with no parameters when the skip button is pressed or if there are no suggestions",
                    },
                    "triggerv75": shared_screen_configurable_trigger_001(
                        "The flow to trigger when the skip button is pressed or there are no suggestions"
                    ),
                    "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V003,
                },
            },
        },
    }

    check_oas_30_schema(schema, require_example=True)

    await cursor.execute(
        """
UPDATE client_screens SET schema=? WHERE slug=?
        """,
        (
            json.dumps(schema, sort_keys=True),
            "start_merge",
        ),
    )

    await purge_client_screen_cache(itgs, slug="start_merge")
