import json
from itgs import Itgs
from lib.client_flows.helper import check_oas_30_schema
from migrations.shared.shared_screen_transition_001 import (
    SHARED_SCREEN_TRANSITION_SCHEMA_V001,
)


async def up(itgs: Itgs) -> None:
    schema = {
        "type": "object",
        "example": {
            "journey": "oseh_j_fAnW7BvVhd0dPbd30snv8A",
        },
        "required": ["journey"],
        "properties": {
            "journey": {
                "type": "string",
                "format": "journey_uid",
                "example": "oseh_j_fAnW7BvVhd0dPbd30snv8A",
                "description": "The journey they are giving feedback on",
            },
            "entrance": SHARED_SCREEN_TRANSITION_SCHEMA_V001,
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
                    "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V001,
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
                        "description": "The client flow trigger, if any, when the first call to action is pressed",
                    },
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
                    "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V001,
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
                        "description": "The client flow trigger, if any, when the second call to action is pressed",
                    },
                },
            },
        },
    }

    check_oas_30_schema(schema, require_example=True)

    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    await cursor.execute(
        "UPDATE client_screens SET schema=? WHERE slug=?",
        (json.dumps(schema, sort_keys=True), "journey_feedback"),
    )
