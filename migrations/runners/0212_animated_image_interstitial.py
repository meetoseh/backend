import json
import secrets
from itgs import Itgs
from lib.client_flows.helper import check_oas_30_schema
from lib.client_flows.screen_flags import ClientScreenFlag
from migrations.shared.shared_screen_exact_dynamic_image_001 import (
    shared_screen_exact_dynamic_image_001,
)
from migrations.shared.shared_screen_text_content_001 import (
    SHARED_SCREEN_TEXT_CONTENT_SCHEMA_V001,
)
from migrations.shared.shared_screen_transition_002 import (
    SHARED_SCREEN_TRANSITION_SCHEMA_V002,
)


async def up(itgs: Itgs) -> None:
    schema = {
        "type": "object",
        "example": {
            "top": "✨ Welcome to Oseh",
            "image1": shared_screen_exact_dynamic_image_001(["image1"])["example"],
            "image2": shared_screen_exact_dynamic_image_001(["image2"])["example"],
            "animation1": {
                "start": {"x": 0, "y": 0, "rotation": 0, "scale": 1, "opacity": 1},
                "parts": [
                    {
                        "param": "x",
                        "initial": 0,
                        "final": 1,
                        "ease": {"type": "standard", "id": "ease"},
                        "delay": 0,
                        "duration": 5,
                    },
                    {
                        "param": "x",
                        "initial": 1,
                        "final": 0,
                        "ease": {"type": "standard", "id": "ease"},
                        "delay": 5,
                        "duration": 5,
                    },
                ],
            },
            "animation2": {
                "start": {"x": 0, "y": 0, "rotation": 0, "scale": 1, "opacity": 1},
                "parts": [
                    {
                        "param": "y",
                        "initial": 0,
                        "final": 1,
                        "ease": {"type": "standard", "id": "ease"},
                        "delay": 0,
                        "duration": 5,
                    },
                    {
                        "param": "y",
                        "initial": 1,
                        "final": 0,
                        "ease": {"type": "standard", "id": "ease"},
                        "delay": 5,
                        "duration": 5,
                    },
                ],
            },
            "content": {
                "type": "screen-text-content",
                "version": 1,
                "parts": [
                    {
                        "type": "header",
                        "value": "Introducing your guide for a more mindful life",
                    },
                    {"type": "spacer", "pixels": 12},
                    {"type": "check", "message": "Share how you’re feeling"},
                    {"type": "spacer", "pixels": 8},
                    {
                        "type": "check",
                        "message": "Receive personalized guidance",
                    },
                    {"type": "spacer", "pixels": 8},
                    {
                        "type": "check",
                        "message": "Reflect and grow",
                    },
                ],
            },
            "height": 300,
            "assumed_content_height": 160,
            "cta": "Continue",
        },
        "required": ["top", "image1", "image2", "animation1", "animation2", "content"],
        "properties": {
            "top": {
                "type": "string",
                "example": "✨ Welcome to Oseh",
                "description": "The top text of the screen",
            },
            "image1": shared_screen_exact_dynamic_image_001(["image1"]),
            "image2": shared_screen_exact_dynamic_image_001(["image2"]),
            "animation1": _animation("Animation for image1"),
            "animation2": _animation("Animation for image2"),
            "height": {
                "type": "integer",
                "format": "int32",
                "example": 300,
                "default": 300,
                "description": "How much height to reserve for the animation. Anything outside this is cut off",
            },
            "content": SHARED_SCREEN_TEXT_CONTENT_SCHEMA_V001,
            "assumed_content_height": {
                "type": "integer",
                "format": "int32",
                "example": 160,
                "default": 160,
                "description": "When computing how much height is available, how much height (in pixels) we reserve for the content",
            },
            "cta": {
                "type": "string",
                "example": "Continue",
                "default": "Continue",
                "description": "The call to action at the bottom of the screen",
            },
            "entrance": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
            "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
            "trigger": {
                "type": "string",
                "format": "flow_slug",
                "nullable": True,
                "example": None,
                "default": None,
                "description": "The flow to trigger when the call to action is pressed",
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
            "animated_image_interstitial",
            "Animated Image Interstitial",
            "WARNING: NOT PERFORMANT ENOUGH FOR PRODUCTION. ONLY IMPLEMENTED IN NATIVE. A screen where two images can undergo property-independent movement, rotation, scaling, and opacity animations",
            json.dumps(schema, sort_keys=True),
            int(
                ClientScreenFlag.SHOWS_IN_ADMIN
                | ClientScreenFlag.SHOWS_ON_ANDROID
                | ClientScreenFlag.SHOWS_ON_IOS
            ),
        ),
    )


def _animation(description: str):
    return {
        "type": "object",
        "example": {
            "start": {"x": 0, "y": 0, "rotation": 0, "scale": 1, "opacity": 1},
            "parts": [
                {
                    "param": "x",
                    "initial": 0,
                    "final": 1,
                    "ease": {"type": "standard", "id": "ease"},
                    "delay": 0,
                    "duration": 5,
                },
                {
                    "param": "x",
                    "initial": 1,
                    "final": 0,
                    "ease": {"type": "standard", "id": "ease"},
                    "delay": 5,
                    "duration": 5,
                },
            ],
        },
        "required": ["start", "parts"],
        "description": description,
        "properties": {
            "start": {
                "type": "object",
                "required": ["x", "y", "rotation", "scale", "opacity"],
                "example": {"x": 0, "y": 0, "rotation": 0, "scale": 1, "opacity": 1},
                "properties": {
                    "x": {
                        "type": "number",
                        "example": 0,
                        "description": "x coordinate, 0-1",
                    },
                    "y": {
                        "type": "number",
                        "example": 0,
                        "description": "y-coordinate, 0-1",
                    },
                    "rotation": {
                        "type": "number",
                        "example": 0,
                        "description": "rotation radians, about center",
                    },
                    "scale": {
                        "type": "number",
                        "example": 1,
                        "description": "scale, 0.5 for half, 1 for normal, 2 for double",
                    },
                    "opacity": {
                        "type": "number",
                        "example": 1,
                        "description": "opacity, 0 for invisible, 1 for fully visible",
                    },
                },
            },
            "parts": {
                "type": "array",
                "description": "The parts of the animation; when multiple parts are animating the same property, the last to start (or the last index) wins",
                "example": [
                    {
                        "param": "x",
                        "initial": 0,
                        "final": 1,
                        "ease": {"type": "standard", "id": "ease"},
                        "delay": 0,
                        "duration": 5,
                    },
                    {
                        "param": "x",
                        "initial": 1,
                        "final": 0,
                        "ease": {"type": "standard", "id": "ease"},
                        "delay": 5,
                        "duration": 5,
                    },
                ],
                "items": {
                    "type": "object",
                    "example": {
                        "param": "x",
                        "initial": 0,
                        "final": 1,
                        "ease": {"type": "standard", "id": "ease"},
                        "delay": 0,
                        "duration": 5,
                    },
                    "required": [
                        "param",
                        "initial",
                        "final",
                        "ease",
                        "delay",
                        "duration",
                    ],
                    "properties": {
                        "param": {
                            "type": "string",
                            "example": "x",
                            "enum": ["x", "y", "rotation", "scale", "opacity"],
                            "description": "which parameter to animate",
                        },
                        "initial": {
                            "type": "number",
                            "example": 0,
                            "description": "initial value when this part starts",
                        },
                        "final": {
                            "type": "number",
                            "example": 1,
                            "description": "final value when this part ends",
                        },
                        "ease": {
                            "type": "object",
                            "example": {"type": "standard", "id": "ease"},
                            "description": "easing function",
                            "x-enum-discriminator": "type",
                            "oneOf": [
                                {
                                    "type": "object",
                                    "description": "Standard easing functions",
                                    "example": {"type": "standard", "id": "ease"},
                                    "required": ["type", "id"],
                                    "properties": {
                                        "type": {
                                            "type": "string",
                                            "example": "standard",
                                            "enum": ["standard"],
                                            "description": "standard easing functions",
                                        },
                                        "id": {
                                            "type": "string",
                                            "example": "ease",
                                            "description": "id of the easing function",
                                            "enum": [
                                                "ease",
                                                "ease-in",
                                                "ease-in-out",
                                                "ease-in-back",
                                                "ease-out-back",
                                                "ease-in-out-back",
                                                "ease-out",
                                                "linear",
                                            ],
                                        },
                                    },
                                },
                                {
                                    "type": "object",
                                    "example": {
                                        "type": "custom-cubic-bezier",
                                        "precompute": True,
                                        "x1": 0.8,
                                        "x2": 0.2,
                                        "x3": 0.2,
                                        "x4": 0.8,
                                    },
                                    "description": "Custom cubic bezier easing function",
                                    "required": [
                                        "type",
                                        "precompute",
                                        "x1",
                                        "x2",
                                        "x3",
                                        "x4",
                                    ],
                                    "properties": {
                                        "type": {
                                            "type": "string",
                                            "example": "custom-cubic-bezier",
                                            "enum": ["custom-cubic-bezier"],
                                            "description": "custom cubic bezier easing function",
                                        },
                                        "precompute": {
                                            "type": "boolean",
                                            "example": True,
                                            "description": "whether to precompute the easing function on the client; reduces stuttering, but the ease is replaced with a linear interpolation until it's ready",
                                        },
                                        "x1": {
                                            "type": "number",
                                            "example": 0.8,
                                            "description": "first dimension of the second point (of the 4 control points)",
                                        },
                                        "x2": {
                                            "type": "number",
                                            "example": 0.2,
                                            "description": "second dimension of the second point (of the 4 control points)",
                                        },
                                        "x3": {
                                            "type": "number",
                                            "example": 0.2,
                                            "description": "first dimension of the third point (of the 4 control points)",
                                        },
                                        "x4": {
                                            "type": "number",
                                            "example": 0.8,
                                            "description": "second dimension of the third point (of the 4 control points)",
                                        },
                                    },
                                },
                            ],
                        },
                        "delay": {
                            "type": "number",
                            "example": 0,
                            "description": "how long in seconds before this part starts",
                        },
                        "duration": {
                            "type": "number",
                            "example": 5,
                            "description": "how long in seconds this part lasts",
                        },
                    },
                },
            },
        },
    }
