import json
import secrets
from itgs import Itgs
from lib.client_flows.helper import check_oas_30_schema
from lib.client_flows.screen_flags import ClientScreenFlag
from migrations.shared.shared_screen_transition_002 import (
    SHARED_SCREEN_TRANSITION_SCHEMA_V002,
)
from migrations.shared.shared_screen_exact_dynamic_image_001 import (
    shared_screen_exact_dynamic_image_001,
)


async def up(itgs: Itgs) -> None:
    schema = {
        "type": "object",
        "example": {},
        "properties": {
            "success": {
                "type": "string",
                "format": "flow_slug",
                "nullable": True,
                "default": None,
                "example": "skip",
                "description": "The flow to trigger if the user allows tracking.",
            },
            "failure": {
                "type": "string",
                "format": "flow_slug",
                "nullable": True,
                "default": None,
                "example": "skip",
                "description": "The flow to trigger if the user denies tracking.",
            },
        },
    }

    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    check_oas_30_schema(schema, require_example=True)

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
            "app_tracking_transparency",
            "App Tracking Transparency",
            "Requests access to the advertising ID on iOS 14+ devices using the native dialog",
            json.dumps(schema, sort_keys=True),
            int(ClientScreenFlag.SHOWS_IN_ADMIN | ClientScreenFlag.SHOWS_ON_IOS),
        ),
    )
