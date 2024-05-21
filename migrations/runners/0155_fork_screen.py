import json
import secrets
from itgs import Itgs
from lib.client_flows.helper import check_oas_30_schema
from lib.client_flows.screen_flags import ClientScreenFlag
from migrations.shared.shared_screen_transition_001 import (
    SHARED_SCREEN_TRANSITION_SCHEMA_V001,
)


async def up(itgs: Itgs) -> None:
    schema = {
        "type": "object",
        "example": {
            "header": "Fork Header",
            "message": "Choose what you want to do",
            "options": [
                {"text": "Option 1", "slug": "option_1"},
                {"text": "Option 2", "slug": "option_2"},
                {"text": "Option 3", "slug": "option_3"},
            ],
        },
        "required": ["header", "message", "options"],
        "properties": {
            "header": {
                "type": "string",
                "example": "Fork Header",
                "description": "Shown prominently",
            },
            "message": {
                "type": "string",
                "example": "Choose what you want to do",
                "description": "Shown below the header, less prominently",
            },
            "options": {
                "type": "array",
                "example": [
                    {"text": "Option 1", "slug": "option_1"},
                    {"text": "Option 2", "slug": "option_2"},
                    {"text": "Option 3", "slug": "option_3"},
                ],
                "minItems": 1,
                "items": {
                    "type": "object",
                    "example": {"text": "Some Option", "slug": "some_option"},
                    "required": ["text", "slug"],
                    "properties": {
                        "text": {
                            "type": "string",
                            "example": "Some Option",
                            "description": "The text to display for the option",
                        },
                        "slug": {
                            "type": "string",
                            "example": "some_option",
                            "description": (
                                "This is stored in the trace in addition to the text and "
                                "trigger when the user chooses an option. Choosing a unique, "
                                "stable value that represents the option will make querying "
                                "responses easier, especially in the face of copy changes."
                            ),
                        },
                        "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V001,
                        "trigger": {
                            "type": "string",
                            "format": "flow_slug",
                            "nullable": True,
                            "example": None,
                            "default": None,
                            "description": "The client flow trigger, if any, when the option is selected",
                        },
                    },
                },
            },
            "entrance": SHARED_SCREEN_TRANSITION_SCHEMA_V001,
        },
    }

    check_oas_30_schema(schema, require_example=True)

    conn = await itgs.conn()
    cursor = conn.cursor()

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
            "fork",
            "Fork",
            "Displays a header, message, and series of options",
            json.dumps(schema, sort_keys=True),
            int(
                ClientScreenFlag.SHOWS_IN_ADMIN
                | ClientScreenFlag.SHOWS_ON_ANDROID
                | ClientScreenFlag.SHOWS_ON_IOS
                | ClientScreenFlag.SHOWS_ON_BROWSER
            ),
        ),
    )
