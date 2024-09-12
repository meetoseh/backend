import json
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
            "entrance": SHARED_SCREEN_TRANSITION_SCHEMA_V003,
            "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V003,
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
                "deprecated": True,
                "description": "The flow to trigger when the call to action is pressed",
            },
            "triggerv75": shared_screen_configurable_trigger_001(
                "The flow to trigger when the call to action is pressed"
            ),
        },
    }

    check_oas_30_schema(schema, require_example=True)

    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    await cursor.execute(
        """
UPDATE client_screens SET schema=? WHERE slug=?
        """,
        (
            json.dumps(schema, sort_keys=True),
            "chat_message_examples",
        ),
    )

    await purge_client_screen_cache(itgs, slug="chat_message_examples")
