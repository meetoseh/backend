import json
from typing import cast
from itgs import Itgs
from lib.client_flows.helper import check_oas_30_schema
from migrations.shared.shared_screen_configurable_trigger_001 import (
    shared_screen_configurable_trigger_001,
)
from migrations.shared.shared_screen_transition_002 import (
    SHARED_SCREEN_TRANSITION_SCHEMA_V002,
)


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    response = await cursor.execute(
        "SELECT uid FROM journeys WHERE deleted_at IS NULL AND special_category IS NULL AND variation_of_journey_id IS NULL ORDER BY created_at DESC, uid ASC LIMIT 1"
    )
    example_journey_uid = (
        cast(str, response.results[0][0]) if response.results else "oseh_j_placeholder"
    )

    schema = {
        "type": "object",
        "example": {
            "journey": example_journey_uid,
        },
        "required": ["journey"],
        "properties": {
            "journey": {
                "type": "string",
                "format": "journey_uid",
                "example": example_journey_uid,
                "description": "The journey they are giving feedback on",
            },
            "entrance": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
            "cta1": {
                "type": "object",
                "default": {"text": "Continue"},
                "example": {"text": "Continue"},
                "required": ["text"],
                "properties": {
                    "text": {
                        "type": "string",
                        "example": "Continue",
                        "description": "The text for the primary continue button",
                    },
                    "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
                    "emotion": {
                        "type": "string",
                        "nullable": True,
                        "default": None,
                        "example": "calm",
                        "description": "If specified, not blank, and trigger is specified, we include this in the client parameters when triggering",
                    },
                    "trigger": {
                        "type": "string",
                        "format": "flow_slug",
                        "nullable": True,
                        "example": None,
                        "default": None,
                        "description": "The client flow trigger, if any, when the first call to action is pressed. Used below version 75 and when triggver75 is not set",
                        "deprecated": True,
                    },
                    "triggerv75": shared_screen_configurable_trigger_001(
                        "How to handle the first call to action, for version 75 and higher",
                    ),
                },
            },
            "cta2": {
                "type": "object",
                "nullable": True,
                "default": None,
                "example": None,
                "required": ["text"],
                "properties": {
                    "text": {
                        "type": "string",
                        "example": "Continue",
                        "description": "The text for the secondary continue button",
                    },
                    "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
                    "emotion": {
                        "type": "string",
                        "nullable": True,
                        "default": None,
                        "example": "calm",
                        "description": "If specified, not blank, and trigger is specified, we include this in the client parameters when triggering",
                    },
                    "trigger": {
                        "type": "string",
                        "format": "flow_slug",
                        "nullable": True,
                        "example": None,
                        "default": None,
                        "description": "The client flow trigger, if any, when the second call to action is pressed. Used in version 74 or lower or when triggerv75 is not set",
                        "deprecated": True,
                    },
                    "triggerv75": shared_screen_configurable_trigger_001(
                        "How to handle the second call to action, for version 75 and higher",
                    ),
                },
            },
        },
    }

    check_oas_30_schema(schema, require_example=True)

    await cursor.execute(
        "UPDATE client_screens SET schema=? WHERE slug=?",
        (json.dumps(schema, sort_keys=True), "journey_feedback"),
    )
