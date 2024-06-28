import json
from itgs import Itgs
from lib.client_flows.helper import check_oas_30_schema


async def up(itgs: Itgs) -> None:
    schema = {
        "type": "object",
        "example": {
            "name": "Timothy",
            "time_of_day": "morning",
            "streak": "3 days",
            "goal": "3 of 5",
            "goal_simple": "5",
            "goal_badge_url": "https://oseh.io/goalBadge/3of5-192h.png",
            "url": "oseh.io#stufff",
            "unsubscribe_url": "https://oseh.io#unsubscribe_url",
        },
        "required": [
            "name",
            "time_of_day",
            "streak",
            "goal",
            "goal_simple",
            "goal_badge_url",
        ],
        "properties": {
            "name": {
                "type": "string",
                "example": "Timothy",
                "description": "The user's given name",
            },
            "time_of_day": {
                "type": "string",
                "enum": ["morning", "afternoon", "evening"],
                "example": "morning",
                "description": "Between 3am and noon - morning. Between noon and 5pm - afternoon. Between 5pm and 3am - evening. This is in the users local timezone.",
            },
            "streak": {
                "type": "string",
                "example": "3 days",
                "description": "The user's current streak",
            },
            "goal": {
                "type": "string",
                "example": "3 of 5",
                "description": "The user's progress towards their goal this week, or 'Not set' if their goal is not set",
            },
            "goal_simple": {
                "type": "string",
                "example": "5",
                "description": "The goal days per week for the user, or '0' if not set",
            },
            "goal_badge_url": {
                "type": "string",
                "example": "https://oseh.io/goalBadge/3of5-192h.png",
                "description": "The URL to the badge image for the user's progress towards their goal this week",
            },
            "url": {
                "type": "string",
                "nullable": True,
                "default": None,
                "example": "oseh.io#stufff",
                "description": "A trackable url, present only for non-push messages",
            },
            "unsubscribe_url": {
                "type": "string",
                "nullable": True,
                "default": None,
                "example": "https://oseh.io#unsubscribe_url",
                "description": "A URL to quickly unsubscribe from daily reminders. Present only for email messages",
            },
            "ss_reset": {
                "type": "boolean",
                "example": False,
                "default": False,
                "description": "True iff we want to return to the beginning of the ordered resettable list",
            },
        },
    }

    check_oas_30_schema(schema, require_example=True)

    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.execute(
        """
UPDATE touch_points
SET event_schema=?
WHERE
    event_slug in (?, ?, ?, ?)
        """,
        (
            json.dumps(schema, sort_keys=True),
            "daily_reminder_almost_miss_goal",
            "daily_reminder_almost_goal",
            "daily_reminder_engaged",
            "daily_reminder_disengaged",
        ),
    )
