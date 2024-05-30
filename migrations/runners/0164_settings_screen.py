import json
import secrets
from typing import Optional
from itgs import Itgs
from lib.client_flows.helper import check_oas_30_schema
from lib.client_flows.screen_flags import ClientScreenFlag


async def up(itgs: Itgs) -> None:
    schema = {
        "type": "object",
        "example": {
            "upgrade": {"trigger": "upgrade_settings"},
            "membership": {"trigger": "membership"},
            "history": {"trigger": "history"},
            "reminders": {"trigger": "reminders"},
            "goal": {"trigger": "set_goal"},
            "support": {"trigger": None},
            "privacy": {"url": "https://www.oseh.com/privacy"},
            "terms": {"url": "https://www.oseh.com/terms"},
            "home": {"trigger": None},
            "series": {"trigger": "view_series_list"},
        },
        "required": [
            "upgrade",
            "membership",
            "history",
            "reminders",
            "goal",
            "support",
            "privacy",
            "terms",
            "home",
            "series",
        ],
        "properties": {
            "upgrade": _trigger(
                "The Upgrade to Oseh+ button if they don't have Oseh+",
                "upgrade_settings",
            ),
            "membership": _trigger(
                "The Manage Membership button if they do have Oseh+", "membership"
            ),
            "history": _trigger(
                "The My Library button where they can see their history", "history"
            ),
            "reminders": _trigger(
                "The Reminders button where they can see their reminders", "reminders"
            ),
            "goal": _trigger(
                "The Goal button where they can set their goal", "set_goal"
            ),
            "support": _trigger(
                "The Support button where they can get support. If the trigger is null, opens their email client to mail hi@oseh.com",
                "support",
            ),
            "privacy": _url("The Privacy Policy link", "https://www.oseh.com/privacy"),
            "terms": _url("The Terms of Service link", "https://www.oseh.com/terms"),
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
            "settings",
            "Settings",
            "The settings screen, primarily visited via the Account button in the bottom nav",
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
        },
        "example": {"trigger": flow_slug},
    }


def _url(description: str, url: str):
    return {
        "type": "object",
        "required": ["url"],
        "description": description,
        "properties": {
            "url": {
                "type": "string",
                "description": f"The URL for {description}",
                "example": url,
            },
        },
        "example": {"url": url},
    }
