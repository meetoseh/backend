import json
import secrets
from itgs import Itgs
from lib.client_flows.screen_flags import ClientScreenFlag


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

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
            "confirmation",
            "Confirmation",
            "A basic vertically centered header text, message, and button.",
            json.dumps(
                {
                    "type": "object",
                    "example": {
                        "header": "Welcome!",
                        "message": "You’re all set up. We hope you enjoy your experience",
                        "trigger": None,
                    },
                    "required": ["header", "message"],
                    "properties": {
                        "header": {"type": "string"},
                        "message": {"type": "string"},
                        "trigger": {
                            "type": "string",
                            "format": "flow_slug",
                            "nullable": True,
                        },
                    },
                },
                sort_keys=True,
            ),
            int(
                ClientScreenFlag.SHOWS_IN_ADMIN
                | ClientScreenFlag.SHOWS_ON_ANDROID
                | ClientScreenFlag.SHOWS_ON_IOS
                | ClientScreenFlag.SHOWS_ON_BROWSER
            ),
        ),
    )
