import json
from itgs import Itgs
from lib.client_flows.helper import check_oas_30_schema
from lib.client_flows.screen_cache import purge_client_screen_cache
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
                "example": None,
                "deprecated": True,
                "description": (
                    "The flow to trigger when an emotion is pressed. If `direct` is `true`, this "
                    "flow is triggered with the emotion and journey in the server parameters. If "
                    "direct is False, the flow is triggered with the emotion in the client parameters."
                ),
            },
            "triggerv75": shared_screen_configurable_trigger_001(
                "The flow to trigger when an emotion is pressed. If direct is true, "
                "prefers to trigger via pop_to_emotion_class with the emotion word as the "
                "emotion parameter and premium as the premium parameter. If direct is false, "
                "prefers the standard pop endpoint with no parameters."
            ),
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
UPDATE client_screens SET schema=? WHERE slug=?
        """,
        (
            json.dumps(schema, sort_keys=True),
            "choose_a_feeling",
        ),
    )

    await purge_client_screen_cache(itgs, slug="choose_a_feeling")
