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
            "header": "A deeper practice starts with Oseh+",
            "checkout": {
                "success": "post_checkout_success",
                "failure": "post_checkout_failure",
            },
        },
        "required": ["checkout"],
        "properties": {
            "header": {
                "type": "string",
                "default": "A deeper practice starts with Oseh+",
                "example": "A deeper practice starts with Oseh+",
                "description": "The big bold text at the top",
            },
            "image": {
                "type": "string",
                "format": "image_uid",
                "example": "oseh_if_qWZHxhR86u_wttPwkoa1Yw",
                "default": "oseh_if_qWZHxhR86u_wttPwkoa1Yw",
                "description": "The image in the background, 410px shorter than the screen height",
                "x-processor": {
                    "job": "runners.screens.upgrade_process_image",
                    "list": "upgrade",
                },
                "x-thumbhash": {"width": 342, "height": 223},
                "x-preview": {"width": 342, "height": 223},
            },
            "entrance": SHARED_SCREEN_TRANSITION_SCHEMA_V001,
            "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V001,
            "back": {
                "type": "string",
                "format": "flow_slug",
                "nullable": True,
                "default": None,
                "example": None,
                "description": "The flow to trigger when the back button is pressed. Triggered with no parameters",
            },
            "checkout": {
                "type": "object",
                "required": ["success", "failure"],
                "example": {
                    "success": "post_checkout_success",
                    "failure": "post_checkout_failure",
                },
                "properties": {
                    "success": {
                        "type": "string",
                        "format": "flow_slug",
                        "enum": ["post_checkout_success"],
                        "example": "post_checkout_success",
                        "description": "The flow to trigger when the checkout is successful. Not configurable on web (always `post_checkout_success`).",
                    },
                    "failure": {
                        "type": "string",
                        "format": "flow_slug",
                        "enum": ["post_checkout_failure"],
                        "example": "post_checkout_failure",
                        "description": "The flow to trigger when the checkout fails. Not configurable on web (always `post_checkout_failure`).",
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
        (json.dumps(schema, sort_keys=True), "upgrade"),
    )
