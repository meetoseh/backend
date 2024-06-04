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
            "journey": "oseh_j_fAnW7BvVhd0dPbd30snv8A",
            "header": "How was your first class?",
            "message": "We use this data to help us tailor your perfect next practice.",
            "background": "dark-gray",
            "cta": {
                "text": "Continue",
                "trigger": {
                    "hated": "feedback_hated",
                    "disliked": "feedback_disliked",
                    "liked": "feedback_liked",
                    "loved": "feedback_loved",
                },
            },
        },
        "required": ["journey", "header", "background", "cta"],
        "properties": {
            "entrance": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
            "journey": {
                "type": "string",
                "format": "journey_uid",
                "example": "oseh_j_fAnW7BvVhd0dPbd30snv8A",
                "description": "The journey that the user is rating",
            },
            "header": {
                "type": "string",
                "example": "How was your first class?",
                "description": "The large header text at the top",
            },
            "message": {
                "type": "string",
                "nullable": True,
                "example": "We use this data to help us tailor your perfect next practice.",
                "default": None,
                "description": "The message below the header.",
            },
            "background": {
                "type": "string",
                "enum": ["journey", "dark-gray"],
                "example": "dark-gray",
                "description": "The background color of the screen. Journey matches the journey blurred background.",
            },
            "cta": {
                "type": "object",
                "required": ["text"],
                "example": {
                    "text": "Continue",
                    "trigger": {
                        "hated": "feedback_hated",
                        "disliked": "feedback_disliked",
                        "liked": "feedback_liked",
                        "loved": "feedback_loved",
                    },
                },
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The text on the call to action button",
                        "example": "Continue",
                    },
                    "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
                    "trigger": {
                        "type": "object",
                        "default": {},
                        "example": {
                            "hated": "feedback_hated",
                            "disliked": "feedback_disliked",
                            "liked": "feedback_liked",
                            "loved": "feedback_loved",
                        },
                        "description": "What to do when the user taps the button, based on their response. No parameters are provided to the triggers.",
                        "properties": {
                            "hated": {
                                "type": "string",
                                "format": "flow_slug",
                                "nullable": True,
                                "default": None,
                                "example": "feedback_hated",
                            },
                            "disliked": {
                                "type": "string",
                                "format": "flow_slug",
                                "nullable": True,
                                "default": None,
                                "example": "feedback_disliked",
                            },
                            "liked": {
                                "type": "string",
                                "format": "flow_slug",
                                "nullable": True,
                                "default": None,
                                "example": "feedback_liked",
                            },
                            "loved": {
                                "type": "string",
                                "format": "flow_slug",
                                "nullable": True,
                                "default": None,
                                "example": "feedback_loved",
                            },
                        },
                    },
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
            "rate_class",
            "Rate Class",
            "Simplified rate a class screen.",
            json.dumps(schema, sort_keys=True),
            int(
                ClientScreenFlag.SHOWS_IN_ADMIN
                | ClientScreenFlag.SHOWS_ON_ANDROID
                | ClientScreenFlag.SHOWS_ON_IOS
                | ClientScreenFlag.SHOWS_ON_BROWSER
            ),
        ),
    )
