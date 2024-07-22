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
            "top": "📃 Feedback",
            "header": "Anything you would like to add?",
            "message": "We value your feedback and read every word!",
            "slug": "generic",
        },
        "required": ["top", "header", "message", "slug"],
        "properties": {
            "top": {
                "type": "string",
                "description": "The text at the top, typically starting with an emoji",
                "example": "📃 Feedback",
            },
            "header": {
                "type": "string",
                "description": "Large prominent text",
                "example": "Anything you would like to add?",
            },
            "message": {
                "type": "string",
                "description": "Text below the header",
                "example": "We value your feedback and read every word!",
            },
            "placeholder": {
                "type": "string",
                "description": "The placeholder text for the feedback input.",
                "example": "Write anything",
                "default": "Write anything",
            },
            "details": {
                "type": "string",
                "description": "Detail text below the input, or null for no details",
                "nullable": True,
                "example": None,
                "default": None,
            },
            "cta": {
                "type": "string",
                "description": "The call to action text",
                "example": "Continue",
                "default": "Continue",
            },
            "cta2": {
                "type": "object",
                "nullable": True,
                "description": "A second call to action, or null for no second call to action",
                "example": {"text": "Skip"},
                "default": None,
                "required": ["text"],
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The text for the call to action",
                        "example": "Skip",
                    },
                    "trigger": {
                        "type": "string",
                        "format": "flow_slug",
                        "nullable": True,
                        "example": None,
                        "default": None,
                        "description": "The flow to trigger when the call to action is pressed",
                    },
                },
            },
            "close": {
                "type": "string",
                "format": "flow_slug",
                "nullable": True,
                "example": None,
                "default": None,
                "description": "The flow to trigger when the close button is pressed",
            },
            "slug": {
                "type": "string",
                "description": "An arbitrary identifier for searching for this feedback later",
                "example": "generic",
            },
            "anonymous": {
                "type": "string",
                "description": """
Determines whether or not to allow anonymous feedback.

- `opt-in`: a checkbox is presented, which is unchecked by default
- `opt-out`: a checkbox is presented, which is checked by default
- `require`: no checkbox is presented and the feedback is anonymized
- `forbid`: no checkbox is presented and the feedback is not anonymized

Generally, unless its `forbid`, details should be used to explain that
we will be able to initially determine the user's identity for abuse
protection, but we will not store / log / use it beyond that.
                """.strip(),
                "example": "opt-in",
                "default": "forbid",
                "enum": ["opt-in", "opt-out", "require", "forbid"],
            },
            "anonymous_label": {
                "type": "string",
                "description": "The label for the anonymous checkbox",
                "example": "Send anonymously",
                "default": "Send anonymously",
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
            "feedback",
            "Feedback",
            "A screen where the user can present feedback and we send that feedback to slack",
            json.dumps(schema, sort_keys=True),
            int(
                ClientScreenFlag.SHOWS_IN_ADMIN
                | ClientScreenFlag.SHOWS_ON_BROWSER
                | ClientScreenFlag.SHOWS_ON_ANDROID
                | ClientScreenFlag.SHOWS_ON_IOS
            ),
        ),
    )
