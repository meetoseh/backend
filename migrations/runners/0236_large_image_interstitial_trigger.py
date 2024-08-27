from itgs import Itgs
from lib.client_flows.helper import check_oas_30_schema
from lib.client_flows.screen_cache import purge_client_screen_cache
from migrations.shared.shared_screen_configurable_trigger_001 import (
    shared_screen_configurable_trigger_001,
)
from migrations.shared.shared_screen_text_content_001 import (
    SHARED_SCREEN_TEXT_CONTENT_SCHEMA_V001,
)
from migrations.shared.shared_screen_transition_002 import (
    SHARED_SCREEN_TRANSITION_SCHEMA_V002,
)
import json


async def up(itgs: Itgs) -> None:
    schema = {
        "type": "object",
        "example": {
            "top": "🔒 Our commitment to your data privacy",
            "image": "oseh_if_qWZHxhR86u_wttPwkoa1Yw",
            "content": {
                "type": "screen-text-content",
                "version": 1,
                "parts": [
                    {"type": "header", "value": "Your data, for your eyes only"},
                    {"type": "spacer", "pixels": 12},
                    {"type": "check", "message": "We will never sell your data"},
                    {"type": "spacer", "pixels": 8},
                    {
                        "type": "check",
                        "message": "You can delete your data any any time",
                    },
                    {"type": "spacer", "pixels": 8},
                    {
                        "type": "check",
                        "message": "Your data is encrypted in transit and at rest",
                    },
                ],
            },
            "assumed_content_height": 160,
            "cta": "Continue",
        },
        "required": ["top", "image", "content"],
        "properties": {
            "top": {
                "type": "string",
                "description": "The message at the top of the screen, typically starting with an emoji and providing context",
                "example": "🔒 Our commitment to your data privacy",
            },
            "image": {
                "type": "string",
                "format": "image_uid",
                "example": "oseh_if_qWZHxhR86u_wttPwkoa1Yw",
                "x-processor": {
                    "job": "runners.screens.large_image_interstitial_process_image",
                    "list": "large_image_interstitial",
                },
                "x-thumbhash": {"width": 342, "height": 390},
                "x-preview": {"width": 342, "height": 237},
                "description": "At least 342 width x 237 height, with thresholds up to 342 width x 390 height based on screen height. For iOS, required 3x resolution (1026x1170)",
            },
            "content": SHARED_SCREEN_TEXT_CONTENT_SCHEMA_V001,
            "assumed_content_height": {
                "type": "integer",
                "format": "int32",
                "example": 160,
                "default": 160,
                "description": "When computing how much height is available, how much height (in pixels) we reserve for the content",
            },
            "cta": {
                "type": "string",
                "example": "Continue",
                "default": "Continue",
                "description": "The call to action at the bottom of the screen",
            },
            "entrance": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
            "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
            "trigger": {
                "type": "string",
                "format": "flow_slug",
                "nullable": True,
                "default": None,
                "example": None,
                "deprecated": True,
                "description": "The flow to trigger when the call to action is tapped",
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
            "large_image_interstitial",
        ),
    )

    await purge_client_screen_cache(itgs, slug="large_image_interstitial")
