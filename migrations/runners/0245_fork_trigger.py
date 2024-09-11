import json
from itgs import Itgs
from lib.client_flows.helper import check_oas_30_schema
from lib.client_flows.screen_cache import purge_client_screen_cache
from migrations.shared.shared_screen_configurable_trigger_001 import (
    shared_screen_configurable_trigger_001,
)
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
                            "deprecated": True,
                            "example": None,
                            "default": None,
                            "description": "The client flow trigger, if any, when the option is selected",
                        },
                        "triggerv75": shared_screen_configurable_trigger_001(
                            "The flow to trigger if this option is pressed."
                        ),
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
UPDATE client_screens SET schema=? WHERE slug=?
        """,
        (
            json.dumps(schema, sort_keys=True),
            "fork",
        ),
    )

    await purge_client_screen_cache(itgs, slug="fork")
