import json
import secrets
from itgs import Itgs
from lib.client_flows.helper import check_oas_30_schema
from lib.client_flows.screen_flags import ClientScreenFlag


async def up(itgs: Itgs) -> None:
    schema = {
        "type": "object",
        "example": {},
        "properties": {
            "trigger": {
                "type": "string",
                "format": "flow_slug",
                "nullable": True,
                "example": None,
                "default": None,
                "description": "The flow to trigger after presenting the popup",
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
            "app_review_request",
            "App Review Request",
            "Presents the native app review request popup, if it can. Note we don't know if a popup was actually presented, and the timing on the traces is meaningless for this determination as the popup is (potentially) presented after the function returns successfully",
            json.dumps(schema, sort_keys=True),
            int(
                ClientScreenFlag.SHOWS_IN_ADMIN
                | ClientScreenFlag.SHOWS_ON_ANDROID
                | ClientScreenFlag.SHOWS_ON_IOS
            ),
        ),
    )
