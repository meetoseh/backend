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
            "header": "A deeper practice starts with Oseh+",
        },
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
        },
    }

    check_oas_30_schema(schema, require_example=True)

    conn = await itgs.conn()
    cursor = conn.cursor("weak")

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
            "upgrade",
            "Upgrade",
            "Displays the current Oseh+ offer for the user",
            json.dumps(schema, sort_keys=True),
            int(
                ClientScreenFlag.SHOWS_IN_ADMIN
                | ClientScreenFlag.SHOWS_ON_ANDROID
                | ClientScreenFlag.SHOWS_ON_IOS
                | ClientScreenFlag.SHOWS_ON_BROWSER
            ),
        ),
    )
