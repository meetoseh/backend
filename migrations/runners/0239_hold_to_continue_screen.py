import json
import secrets
from itgs import Itgs
from lib.client_flows.helper import check_oas_30_schema
from lib.client_flows.screen_flags import ClientScreenFlag
from migrations.shared.shared_screen_configurable_trigger_001 import (
    shared_screen_configurable_trigger_001,
)
from migrations.shared.shared_screen_transition_002 import (
    SHARED_SCREEN_TRANSITION_SCHEMA_V002,
)


async def up(itgs: Itgs) -> None:
    schema = {
        "type": "object",
        "example": {
            "image": "oseh_if_placeholder",
            "instructions": "When you are ready, hold the calm face to continue",
            "title": "You’re absolutely right!",
            "body": "Now let’s explore a simple step to help you feel your best",
        },
        "required": ["image", "instructions", "title", "body"],
        "properties": {
            "entrance": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
            "image": {
                "type": "string",
                "format": "image_uid",
                "example": "oseh_if_qWZHxhR86u_wttPwkoa1Yw",
                "x-processor": {
                    "job": "runners.screens.hold_to_continue_process_image",
                    "list": "exact_dynamic@200x200",
                },
                "x-thumbhash": {"width": 80, "height": 80},
                "x-preview": {"width": 80, "height": 80},
                "description": "Shown initially at 80px by 80px, grows to 200px by 200px. Thus, for iOS (3x resolution), need 600px by 600px",
            },
            "instructions": {
                "type": "string",
                "example": "When you are ready, hold the calm face to continue",
                "description": "Small text below the image",
            },
            "hold_time_ms": {
                "type": "integer",
                "example": 500,
                "default": 500,
                "minimum": 0,
                "description": "How long the user must hold the button to continue; 0 for just a tap",
            },
            "hold_vibration": {
                "type": "array",
                "example": [100, 400],
                "default": [100, 400],
                "description": (
                    "Vibration pattern that plays while the user is holding the button. "
                    "The first element is how long to vibrate immediately after the tap, "
                    "the next is how long to wait before vibrating again, then how long to vibrate again, "
                    "repeating. So [100, 300, 100] would vibrate for 100ms, wait 300ms, vibrate for 100ms. "
                    "This vibration pattern is not repeated and is aborted if the user releases the button "
                    "or the hold time is reached, so should match the hold time. NOTE: on ios and android "
                    "this is ignored; if a positive hold time is specified, we use a selection changed haptic "
                    "at the start."
                ),
                "items": {
                    "type": "integer",
                    "example": 100,
                    "minimum": 0,
                    "description": "Duration in milliseconds",
                },
            },
            "continue_vibration": {
                "type": "array",
                "example": [0, 400, 100],
                "default": [0, 400, 100],
                "description": (
                    "After the hold time is reached we play this vibration pattern one time while "
                    "animating the image. We will determine the duration of the animation relative to "
                    "the total vibration time, so for example if you don't want vibration but want about "
                    "a 350ms animation, use [0, 350]. Describes in alternating pairs of (on, off) times. "
                    "NOTE: On ios and android, the duration is considered but the pattern is ignored, "
                    "instead we use the success feedback at the start"
                ),
                "items": {
                    "type": "integer",
                    "example": 100,
                    "minimum": 0,
                    "description": "Duration in milliseconds",
                },
            },
            "title": {
                "type": "string",
                "example": "You’re absolutely right!",
                "description": "Title in large text below the instructions",
            },
            "body": {
                "type": "string",
                "example": "Now let’s explore a simple step to help you feel your best",
                "description": "Body text below the title",
            },
            "trigger": shared_screen_configurable_trigger_001(
                "Triggered after finishing the continue animation"
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
            "hold_to_continue",
            "Hold to Continue",
            "A more interesting variant of the confirmation screen, where the user has to press and hold to continue, receiving an animation and haptics. Supporting in v87 and higher",
            json.dumps(schema, sort_keys=True),
            int(
                ClientScreenFlag.SHOWS_IN_ADMIN
                | ClientScreenFlag.SHOWS_ON_BROWSER
                | ClientScreenFlag.SHOWS_ON_ANDROID
                | ClientScreenFlag.SHOWS_ON_IOS
            ),
        ),
    )
