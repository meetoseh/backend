import json
import secrets
from typing import Optional
from itgs import Itgs
from lib.client_flows.helper import check_oas_30_schema
from lib.client_flows.screen_flags import ClientScreenFlag
from migrations.shared.shared_screen_transition_002 import (
    SHARED_SCREEN_TRANSITION_SCHEMA_V002,
)


async def up(itgs: Itgs) -> None:
    schema = {
        "type": "object",
        "example": {
            "back": {"trigger": "account"},
            "journey": {"trigger": "journey"},
            "favorites": {"trigger": "favorites"},
            "owned": {"trigger": "owned"},
            "home": {"trigger": None},
            "series": {"trigger": "view_series_list"},
        },
        "required": [
            "back",
            "journey",
            "favorites",
            "owned",
            "home",
            "series",
        ],
        "properties": {
            "entrance": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
            "back": _trigger("The Back button in the top left", "account"),
            "journey": _trigger(
                "one of the journeys in the list. Triggered with server parameter `journey`",
                "journey",
            ),
            "favorites": _trigger("The Favorites button in the top nav", "favorites"),
            "owned": _trigger("The Owned button in the top nav", "owned"),
            "home": _trigger("The Home button in the bottom nav", None),
            "series": _trigger(
                "The Series button in the bottom nav", "view_series_list"
            ),
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
            "history",
            "History",
            "The list of the journeys the user has taken.",
            json.dumps(schema, sort_keys=True),
            int(
                ClientScreenFlag.SHOWS_IN_ADMIN
                | ClientScreenFlag.SHOWS_ON_ANDROID
                | ClientScreenFlag.SHOWS_ON_IOS
                | ClientScreenFlag.SHOWS_ON_BROWSER
            ),
        ),
    )


def _trigger(description: str, flow_slug: Optional[str]):
    return {
        "type": "object",
        "required": ["trigger"],
        "description": description,
        "properties": {
            "trigger": {
                "type": "string",
                "format": "flow_slug",
                "nullable": True,
                "description": f"Triggered when they click {description[0].lower() + description[1:]}",
                "example": flow_slug,
            },
            "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
        },
        "example": {"trigger": flow_slug},
    }
