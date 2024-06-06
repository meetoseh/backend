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
            "title": "Your journey to a more mindful life begins now.",
            "subtitle": "Setup complete",
            "cta": {"text": "I’m Ready"},
        },
        "required": ["title", "cta"],
        "properties": {
            "entrance": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
            "title": {
                "type": "string",
                "example": "Your journey to a more mindful life begins now.",
                "description": "The large text",
            },
            "subtitle": {
                "type": "string",
                "nullable": True,
                "default": None,
                "example": "Setup complete",
                "description": "The small text above the title.",
            },
            "cta": {
                "type": "object",
                "example": {"text": "I’m Ready"},
                "required": ["text"],
                "properties": {
                    "text": {
                        "type": "string",
                        "example": "I’m Ready",
                        "description": "The text on the call to action button",
                    },
                    "trigger": {
                        "type": "string",
                        "format": "flow_slug",
                        "nullable": True,
                        "default": None,
                        "example": None,
                        "description": "The flow to trigger with no parameters",
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
            "completion",
            "Completion",
            "Similar to a confirmation screen, but with confetti",
            json.dumps(schema, sort_keys=True),
            int(
                ClientScreenFlag.SHOWS_IN_ADMIN
                | ClientScreenFlag.SHOWS_ON_ANDROID
                | ClientScreenFlag.SHOWS_ON_IOS
                | ClientScreenFlag.SHOWS_ON_BROWSER
            ),
        ),
    )
