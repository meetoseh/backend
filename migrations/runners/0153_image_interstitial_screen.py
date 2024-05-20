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
            "top": "✅ Interstitial Top Message",
            "image": "oseh_if_qWZHxhR86u_wttPwkoa1Yw",
            "header": "Interstitial Header",
            "message": "The message of the interstitial.",
            "cta": "Continue",
            "entrance": {"type": "fade", "ms": 350},
            "exit": {"type": "fade", "ms": 350},
            "trigger": None,
        },
        "required": ["top", "image", "header", "message"],
        "properties": {
            "top": {
                "type": "string",
                "example": "✅ Interstitial Top Message",
                "description": "Small text at the top-left",
            },
            "image": {
                "type": "string",
                "format": "image_uid",
                "example": "oseh_if_qWZHxhR86u_wttPwkoa1Yw",
                "x-processor": {
                    "job": "runners.screens.image_interstitial_process_image",
                    "list": "image_interstitial",
                },
                "x-thumbhash": {"width": 342, "height": 215},
                "x-preview": {"width": 342, "height": 215},
                "description": "342 width x 215 height image above the header; for iOS, required 3x resolution (1026x645)",
            },
            "header": {"type": "string", "example": "Interstitial Header"},
            "message": {
                "type": "string",
                "example": "The message of the interstitial.",
            },
            "cta": {
                "type": "string",
                "example": "Continue",
                "default": "Continue",
                "description": "The call-to-action, i.e., the button text",
            },
            "entrance": SHARED_SCREEN_TRANSITION_SCHEMA_V001,
            "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V001,
            "trigger": {
                "type": "string",
                "format": "flow_slug",
                "nullable": True,
                "example": None,
                "default": None,
            },
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
            "image_interstitial",
            "Image Interstitial",
            "A basic image interstitial with a top message, image, header, message, and button.",
            json.dumps(schema, sort_keys=True),
            int(
                ClientScreenFlag.SHOWS_IN_ADMIN
                | ClientScreenFlag.SHOWS_ON_ANDROID
                | ClientScreenFlag.SHOWS_ON_IOS
                | ClientScreenFlag.SHOWS_ON_BROWSER
            ),
        ),
    )
