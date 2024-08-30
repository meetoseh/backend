from itgs import Itgs
from lib.client_flows.helper import check_oas_30_schema
from lib.client_flows.screen_cache import purge_client_screen_cache
from migrations.shared.shared_screen_configurable_trigger_001 import (
    shared_screen_configurable_trigger_001,
)
import json


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
                "deprecated": True,
                "description": "The flow to trigger after presenting the popup",
            },
            "triggerv75": shared_screen_configurable_trigger_001(
                "The flow to trigger after presenting the popup, for version 75 and higher",
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
            "app_review_request",
        ),
    )

    await purge_client_screen_cache(itgs, slug="app_review_request")
