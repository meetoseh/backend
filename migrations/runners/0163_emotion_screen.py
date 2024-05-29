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
            "header": "You want to feel",
            "emotion": "calm",
            "back": {"trigger": None},
            "short": {"trigger": "journey", "text": "Take a 1-minute class"},
            "long": {"trigger": "journey", "text": "Take a longer class"},
        },
        "required": ["header", "emotion"],
        "properties": {
            "header": {
                "type": "string",
                "example": "You want to feel",
                "description": "The header text for the screen, shown above the emotion",
            },
            "emotion": {
                "type": "string",
                "example": "calm",
                "description": "The emotion word that we will find a class related to",
            },
            "subheader": {
                "type": "string",
                "nullable": True,
                "default": None,
                "example": "Access our 1-minute classes entirely for free, or upgrade to unlock longer classes",
                "description": "The subheader text for the screen, shown below the header",
            },
            "entrance": SHARED_SCREEN_TRANSITION_SCHEMA_V001,
            "back": {
                "type": "object",
                "nullable": True,
                "default": None,
                "required": ["trigger"],
                "example": {"trigger": None},
                "description": "When back is not null a back button is shown in the upper left",
                "properties": {
                    "trigger": {
                        "type": "string",
                        "format": "flow_slug",
                        "nullable": True,
                        "example": "home",
                        "description": "Triggered with no parameters if they tap the back button.",
                    },
                    "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V001,
                },
            },
            "short": {
                "type": "object",
                "nullable": True,
                "default": None,
                "required": ["trigger", "text"],
                "example": {"trigger": "journey", "text": "Take a 1-minute class"},
                "description": "When provided, a button to take a 1 minute class is shown with these properties.",
                "properties": {
                    "trigger": {
                        "type": "string",
                        "format": "flow_slug",
                        "nullable": True,
                        "example": "home",
                        "description": "Triggered with server parameters journey and emotion; the journey will be a 1-minute one",
                    },
                    "text": {
                        "type": "string",
                        "example": "Take a 1-minute class",
                        "description": "The text for the button",
                    },
                    "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V001,
                },
            },
            "long": {
                "type": "object",
                "nullable": True,
                "default": None,
                "required": ["trigger", "text"],
                "example": {"trigger": "journey", "text": "Take a longer class"},
                "description": "When provided, a button to take a premium is shown with these properties.",
                "properties": {
                    "trigger": {
                        "type": "string",
                        "format": "flow_slug",
                        "nullable": True,
                        "example": "journey",
                        "description": "Only used if they have Oseh+. Triggered with server parameters journey and emotion. The journey is premium.",
                    },
                    "upgrade_trigger": {
                        "type": "string",
                        "format": "flow_slug",
                        "default": "upgrade_longer_classes",
                        "example": "upgrade_longer_classes",
                        "enum": ["upgrade_longer_classes"],
                        "description": "Not currently editable. The flow to trigger if they press this button but do not have Oseh+. Triggered with no parameters.",
                    },
                    "text": {
                        "type": "string",
                        "example": "Take a longer class",
                        "description": "The text for the button",
                    },
                    "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V001,
                },
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
            "emotion",
            "Emotion",
            "Highlights an emotion word and lets the user take a related class",
            json.dumps(schema, sort_keys=True),
            int(
                ClientScreenFlag.SHOWS_IN_ADMIN
                | ClientScreenFlag.SHOWS_ON_ANDROID
                | ClientScreenFlag.SHOWS_ON_IOS
                | ClientScreenFlag.SHOWS_ON_BROWSER
            ),
        ),
    )
