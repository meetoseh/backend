import json
import secrets
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
            "title": "Check-in",
            "focus": "none",
            "back": {"type": "x"},
            "upgrade_trigger": "journal_upgrade_for_journey",
            "journey_trigger": "journal_journey",
        },
        "required": ["title", "upgrade_trigger", "journey_trigger"],
        "properties": {
            "title": {
                "type": "string",
                "description": "The title in the top nav",
                "example": "Check-in",
            },
            "focus": {
                "type": "string",
                "description": "focus to focus the input as soon as possible, false not to",
                "enum": ["none", "input"],
                "default": "none",
                "example": "none",
            },
            "back": {
                "type": "object",
                "x-enum-discriminator": "type",
                "description": "How the user can close the screen",
                "example": {"type": "x"},
                "default": {"type": "x"},
                "oneOf": [
                    {
                        "type": "object",
                        "description": "Show a left caret button in the upper left",
                        "required": ["type"],
                        "example": {"type": "back"},
                        "properties": {
                            "type": {
                                "type": "string",
                                "description": "Show a left caret button in the upper left",
                                "enum": ["back"],
                                "example": "back",
                            },
                            "trigger": {
                                "type": "string",
                                "nullable": True,
                                "format": "flow_slug",
                                "description": "The client flow to trigger with no parameters when the back button is pressed",
                                "default": None,
                                "example": None,
                            },
                        },
                    },
                    {
                        "type": "object",
                        "description": "Show an x button in the upper right",
                        "required": ["type"],
                        "example": {"type": "x"},
                        "properties": {
                            "type": {
                                "type": "string",
                                "description": "Show an x button in the upper right",
                                "enum": ["x"],
                                "example": "x",
                            },
                            "trigger": {
                                "type": "string",
                                "nullable": True,
                                "format": "flow_slug",
                                "description": "The client flow to trigger with no parameters when the close button is pressed",
                                "default": None,
                                "example": None,
                            },
                        },
                    },
                    {
                        "type": "object",
                        "description": "There is no way to exit the screen except if the system response includes a link",
                        "required": ["type"],
                        "example": {"type": "none"},
                        "properties": {
                            "type": {
                                "type": "string",
                                "description": "There is no way to exit the screen except if the system response includes a link",
                                "enum": ["none"],
                                "example": "none",
                            }
                        },
                    },
                ],
            },
            "upgrade_trigger": {
                "type": "string",
                "format": "flow_slug",
                "description": "The client flow to trigger when the user taps a journey that requires Oseh+, but they do not have Oseh+. For now, must always be `journal_upgrade_for_journey`. Includes `journey_uid` in the server parameters",
                "example": "journal_upgrade_for_journey",
                "enum": ["journal_upgrade_for_journey"],
            },
            "journey_trigger": {
                "type": "string",
                "format": "flow_slug",
                "description": "The client flow to trigger when the user taps a journey that either does not require Oseh+, or does require Oseh+ but the user has Oseh+. Includes `journey_uid` in the server parameters",
                "example": "journal_journey",
            },
            "entrance": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
            "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
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
            "journal_chat",
            "Journal Chat",
            "The user receives a greeting and can respond",
            json.dumps(schema, sort_keys=True),
            int(
                ClientScreenFlag.SHOWS_IN_ADMIN
                | ClientScreenFlag.SHOWS_ON_BROWSER
                | ClientScreenFlag.SHOWS_ON_ANDROID
                | ClientScreenFlag.SHOWS_ON_IOS
            ),
        ),
    )
