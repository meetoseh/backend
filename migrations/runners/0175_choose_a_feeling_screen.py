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
            "top": "🥇 First class",
            "header": "Choose a feeling",
            "message": "Select an emotion, and we'll curate the perfect one-minute class just for you.",
            "trigger": "journey",
            "direct": True,
            "premium": False,
        },
        "required": ["top", "header", "direct", "premium"],
        "properties": {
            "entrance": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
            "top": {
                "type": "string",
                "example": "🥇 First class",
                "description": "The text at the top of the screen that provides context",
            },
            "header": {
                "type": "string",
                "example": "Choose a feeling",
                "description": "The wording of the question",
            },
            "message": {
                "type": "string",
                "nullable": True,
                "example": "Select an emotion, and we'll curate the perfect one-minute class just for you.",
                "default": None,
                "description": "The message below the header that provides context for the question",
            },
            "trigger": {
                "type": "string",
                "format": "flow_slug",
                "nullable": True,
                "default": None,
                "example": "journey",
                "description": (
                    "The flow to trigger when an emotion is pressed. If `direct` is `true`, this "
                    "flow is triggered with the emotion and journey in the server parameters. If "
                    "direct is False, the flow is triggered with the emotion in the client parameters."
                ),
            },
            "direct": {
                "type": "boolean",
                "example": True,
                "description": (
                    "True if the flow should be triggered with the emotion and journey in the server "
                    "parameters, false if the flow should be triggered with the emotion in the client parameters."
                ),
            },
            "premium": {
                "type": "boolean",
                "example": False,
                "description": "Only relevant if `direct` is `true`. True if a premium class should be requested, false for a regular class",
            },
            "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
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
            "choose_a_feeling",
            "Choose A Feeling",
            "Allows the user to choose an emotion.",
            json.dumps(schema, sort_keys=True),
            int(
                ClientScreenFlag.SHOWS_IN_ADMIN
                | ClientScreenFlag.SHOWS_ON_ANDROID
                | ClientScreenFlag.SHOWS_ON_IOS
                | ClientScreenFlag.SHOWS_ON_BROWSER
            ),
        ),
    )
