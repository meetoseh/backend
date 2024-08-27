from itgs import Itgs
from lib.client_flows.helper import check_oas_30_schema
from lib.client_flows.screen_cache import purge_client_screen_cache
from migrations.shared.shared_screen_configurable_trigger_001 import (
    shared_screen_configurable_trigger_001,
)
from migrations.shared.shared_screen_transition_002 import (
    SHARED_SCREEN_TRANSITION_SCHEMA_V002,
)
import json


async def up(itgs: Itgs) -> None:
    schema = {
        "type": "object",
        "example": {
            "header": "Welcome!",
            "message": "You’re all set up. We hope you enjoy your experience",
            "cta": "Get Started",
            "entrance": {"type": "fade", "ms": 350},
            "exit": {"type": "fade", "ms": 350},
            "trigger": None,
        },
        "required": ["header", "message"],
        "properties": {
            "header": {"type": "string", "example": "Welcome!"},
            "message": {
                "type": "string",
                "example": "You’re all set up. We hope you enjoy your experience",
            },
            "cta": {
                "type": "string",
                "example": "Ok",
                "default": "Ok",
                "description": "The call-to-action, i.e., the button text",
            },
            "entrance": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
            "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
            "trigger": {
                "type": "string",
                "format": "flow_slug",
                "nullable": True,
                "example": None,
                "default": None,
                "deprecated": True,
            },
            "triggerv75": shared_screen_configurable_trigger_001(
                "How to handle the call to action, for version 75 and higher",
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
            "confirmation",
        ),
    )

    await purge_client_screen_cache(itgs, slug="confirmation")
