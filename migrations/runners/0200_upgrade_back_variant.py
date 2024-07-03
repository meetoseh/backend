import json
from typing import Optional
from itgs import Itgs
from lib.client_flows.helper import check_oas_30_schema
from lib.client_flows.screen_cache import purge_client_screen_cache
from migrations.shared.shared_screen_transition_002 import (
    SHARED_SCREEN_TRANSITION_SCHEMA_V002,
)


async def up(itgs: Itgs) -> None:
    example = {
        "trial": {
            "days7": {
                "header": "Your 7 day free trial",
                "body": {
                    "type": "sequence",
                    "items": [
                        {
                            "icon": "🔓",
                            "title": "Today: Get Instant Access",
                            "body": "Start reducing anxiety, enhancing focus, and improving sleep with Oseh+.",
                        },
                        {
                            "icon": "🧭",
                            "title": "Tomorrow: Discover More",
                            "body": "Explore 100s of classes and enjoy all of our longer sessions.",
                        },
                        {
                            "icon": "🚀",
                            "title": "Day 6: Maximize Your Benefits",
                            "body": "Embark on a mindful journey with one of our series and learn new techniques.",
                        },
                        {
                            "icon": "🌟",
                            "title": "Day 7: Trial Ends",
                            "body": "Your free trial will end. Cancel anytime before to avoid charges.",
                        },
                    ],
                },
            },
            "default": {
                "header": "Your [trial_interval_count] [trial_interval_unit_singular] free trial",
                "image": "oseh_if_qWZHxhR86u_wttPwkoa1Yw",
                "body": {
                    "type": "checklist",
                    "items": [
                        "Access 100s of expert-led classes",
                        "Reduce anxiety, enhance focus and improve sleep",
                        "Access all series and longer classes",
                    ],
                },
            },
        },
        "immediate": {
            "header": "A deeper practice starts with Oseh+",
            "image": "oseh_if_qWZHxhR86u_wttPwkoa1Yw",
            "body": {
                "type": "checklist",
                "items": [
                    "Access 100s of expert-led classes",
                    "Reduce anxiety, enhance focus and improve sleep",
                    "Access all series and longer classes",
                ],
            },
        },
        "checkout": {
            "success": "post_checkout_success",
            "failure": "post_checkout_failure",
        },
        "back_variant": "x",
    }
    schema = {
        "type": "object",
        "example": example,
        "required": ["checkout"],
        "properties": {
            "header": {
                "type": "string",
                "default": "A deeper practice starts with Oseh+",
                "example": "A deeper practice starts with Oseh+",
                "description": "The big bold text at the top, for older versions of the app",
                "deprecated": True,
            },
            "image": {
                "type": "string",
                "format": "image_uid",
                "example": "oseh_if_qWZHxhR86u_wttPwkoa1Yw",
                "default": "oseh_if_qWZHxhR86u_wttPwkoa1Yw",
                "description": "The image in the background, 410px shorter than the screen height, for older versions of the app",
                "x-processor": {
                    "job": "runners.screens.upgrade_process_image",
                    "list": "upgrade",
                },
                "x-thumbhash": {"width": 342, "height": 223},
                "x-preview": {"width": 342, "height": 223},
                "deprecated": True,
            },
            "trial": {
                "type": "object",
                "description": "Configures what to show if there is a trial available",
                "example": example["trial"],
                "default": example["trial"],
                "properties": {
                    "days7": upgrade_copy(
                        "The content to show if the trial is 7 days long",
                        default=example["trial"]["days7"],
                    ),
                    "default": upgrade_copy(
                        "The content to show if the trial is of any other length",
                        default=example["trial"]["default"],
                    ),
                },
            },
            "immediate": upgrade_copy(
                "The content to show if there is no trial available",
                default=example["immediate"],
            ),
            "entrance": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
            "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
            "back": {
                "type": "string",
                "format": "flow_slug",
                "nullable": True,
                "default": None,
                "example": None,
                "description": "The flow to trigger when the back button is pressed. Triggered with no parameters",
            },
            "back_variant": {
                "type": "string",
                "default": "x",
                "example": "x",
                "enum": ["back", "x"],
                "description": "The variant of the back button. `back` shows a back arrow at the top left, `x` shows an X at the top right. Requires app version 1.6.7+ (released July 3rd, 2024) (previously: always back)",
            },
            "checkout": {
                "type": "object",
                "required": ["success", "failure"],
                "example": {
                    "success": "post_checkout_success",
                    "failure": "post_checkout_failure",
                },
                "properties": {
                    "success": {
                        "type": "string",
                        "format": "flow_slug",
                        "enum": ["post_checkout_success"],
                        "example": "post_checkout_success",
                        "description": "The flow to trigger when the checkout is successful. Not configurable on web (always `post_checkout_success`).",
                    },
                    "failure": {
                        "type": "string",
                        "format": "flow_slug",
                        "enum": ["post_checkout_failure"],
                        "example": "post_checkout_failure",
                        "description": "The flow to trigger when the checkout fails. Not configurable on web (always `post_checkout_failure`).",
                    },
                },
            },
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
            "upgrade",
        ),
    )

    await purge_client_screen_cache(itgs, slug="upgrade")


def upgrade_copy(description: str, default: Optional[dict] = None):
    if default is None:
        default = {
            "header": "A deeper practice starts with Oseh+",
            "image": "oseh_if_qWZHxhR86u_wttPwkoa1Yw",
            "body": {
                "type": "checklist",
                "items": [
                    "Access 100s of expert-led classes",
                    "Reduce anxiety, enhance focus and improve sleep",
                    "Access all series and longer classes",
                ],
            },
        }

    return {
        "type": "object",
        "description": description,
        "required": ["header", "body"],
        "default": default,
        "example": default,
        "properties": {
            "header": {
                "type": "string",
                "example": default["header"],
                "description": (
                    "The big bold text at the top. If you know a trial is present, you can use:\n"
                    "- [trial_interval_count] - ex: '7', the number of intervals in the trial\n"
                    "- [trial_interval_unit_autoplural] - ex: 'days', the unit of the trial interval, plural iff count is not 1\n"
                    "- [trial_interval_unit_singular] - ex: 'day', the unit of the trial interval, singular\n"
                ),
            },
            "image": {
                "type": "string",
                "format": "image_uid",
                "nullable": True,
                "default": default.get("image"),
                "example": "oseh_if_qWZHxhR86u_wttPwkoa1Yw",
                "description": "The image in the background, 410px shorter than the screen height",
                "x-processor": {
                    "job": "runners.screens.upgrade_process_image",
                    "list": "upgrade",
                },
                "x-thumbhash": {"width": 342, "height": 223},
                "x-preview": {"width": 342, "height": 223},
            },
            "body": {
                "type": "object",
                "x-enum-discriminator": "type",
                "example": default["body"],
                "oneOf": [
                    {
                        "type": "object",
                        "description": "Shows a basic checklist",
                        "required": ["type", "items"],
                        "example": {
                            "type": "checklist",
                            "items": [
                                "Access 100s of expert-led classes",
                                "Reduce anxiety, enhance focus and improve sleep",
                                "Access all series and longer classes",
                            ],
                        },
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": ["checklist"],
                                "example": "checklist",
                                "description": "Show a checklist of items",
                            },
                            "items": {
                                "type": "array",
                                "description": "The items to show in the checklist",
                                "example": [
                                    "Access 100s of expert-led classes",
                                    "Reduce anxiety, enhance focus and improve sleep",
                                    "Access all series and longer classes",
                                ],
                                "items": {
                                    "type": "string",
                                    "example": "Access 100s of expert-led classes",
                                },
                            },
                        },
                    },
                    {
                        "type": "object",
                        "description": "Shows a sequence of items",
                        "required": ["type", "items"],
                        "example": {
                            "type": "sequence",
                            "items": [
                                {
                                    "icon": "🔓",
                                    "title": "Today: Get Instant Access",
                                    "body": "Start reducing anxiety, enhancing focus, and improving sleep with Oseh+.",
                                },
                                {
                                    "icon": "🧭",
                                    "title": "Tomorrow: Discover More",
                                    "body": "Explore 100s of classes and enjoy all of our longer sessions.",
                                },
                                {
                                    "icon": "🚀",
                                    "title": "Day 6: Maximize Your Benefits",
                                    "body": "Embark on a mindful journey with one of our series and learn new techniques.",
                                },
                                {
                                    "icon": "🌟",
                                    "title": "Day 7: Trial Ends",
                                    "body": "Your free trial will end. Cancel anytime before to avoid charges.",
                                },
                            ],
                        },
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": ["sequence"],
                                "example": "sequence",
                                "description": "Show a sequence of items",
                            },
                            "items": {
                                "type": "array",
                                "example": [
                                    {
                                        "icon": "🔓",
                                        "title": "Today: Get Instant Access",
                                        "body": "Start reducing anxiety, enhancing focus, and improving sleep with Oseh+.",
                                    },
                                    {
                                        "icon": "🧭",
                                        "title": "Tomorrow: Discover More",
                                        "body": "Explore 100s of classes and enjoy all of our longer sessions.",
                                    },
                                    {
                                        "icon": "🚀",
                                        "title": "Day 6: Maximize Your Benefits",
                                        "body": "Embark on a mindful journey with one of our series and learn new techniques.",
                                    },
                                    {
                                        "icon": "🌟",
                                        "title": "Day 7: Trial Ends",
                                        "body": "Your free trial will end. Cancel anytime before to avoid charges.",
                                    },
                                ],
                                "items": {
                                    "type": "object",
                                    "required": ["icon", "title", "body"],
                                    "example": {
                                        "icon": "🔓",
                                        "title": "Today: Get Instant Access",
                                        "body": "Start reducing anxiety, enhancing focus, and improving sleep with Oseh+.",
                                    },
                                    "properties": {
                                        "icon": {
                                            "type": "string",
                                            "example": "🔓",
                                            "description": "The icon to show next to the title",
                                        },
                                        "title": {
                                            "type": "string",
                                            "example": "Today: Get Instant Access",
                                            "description": "The title of the item",
                                        },
                                        "body": {
                                            "type": "string",
                                            "example": "Start reducing anxiety, enhancing focus, and improving sleep with Oseh+.",
                                            "description": "The body of the item",
                                        },
                                    },
                                },
                            },
                        },
                    },
                ],
            },
        },
    }
