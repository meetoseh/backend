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
            "header": "Merge Accounts",
            "message": "To merge your two accounts please let us know where you would like to receive your daily reminders.  You can review your reminder settings after merging your account.",
            "conflict": {
                "email": None,
                "phone": {
                    "original": [
                        {
                            "phone_number": "+15555555551",
                            "suppressed": False,
                            "verified": True,
                            "enabled": True,
                        }
                    ],
                    "merging": [
                        {
                            "phone_number": "+15555555552",
                            "suppressed": False,
                            "verified": True,
                            "enabled": True,
                        }
                    ],
                    "original_settings": {
                        "days_of_week": ["Monday"],
                        "start_time": 21600,
                        "end_time": 28800,
                    },
                    "merging_settings": {
                        "days_of_week": ["Tuesday"],
                        "start_time": 21600,
                        "end_time": 28800,
                    },
                },
                "merge_jwt": "token",
            },
            "cta": {
                "text": "Merge",
            },
            "expired": {"trigger": "start_merge"},
        },
        "required": ["header", "conflict", "cta"],
        "properties": {
            "entrance": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
            "header": {
                "type": "string",
                "example": "Merge Accounts",
                "description": "The large header text at the top",
            },
            "message": {
                "type": "string",
                "nullable": True,
                "default": None,
                "example": "To merge your two accounts please let us know where you would like to receive your daily reminders. You can review your reminder settings after merging your account.",
                "description": "The message below the header.",
            },
            "conflict": {
                "type": "object",
                "description": "This screen is intended for the `merge_confirmation_required` flow, where this can copy server.conflict",
                "example": {
                    "email": None,
                    "phone": {
                        "original": [
                            {
                                "phone_number": "+15555555551",
                                "suppressed": False,
                                "verified": True,
                                "enabled": True,
                            }
                        ],
                        "merging": [
                            {
                                "phone_number": "+15555555552",
                                "suppressed": False,
                                "verified": True,
                                "enabled": True,
                            }
                        ],
                        "original_settings": {
                            "days_of_week": ["Monday"],
                            "start_time": 21600,
                            "end_time": 28800,
                        },
                        "merging_settings": {
                            "days_of_week": ["Tuesday"],
                            "start_time": 21600,
                            "end_time": 28800,
                        },
                    },
                    "merge_jwt": "token",
                },
                "additionalProperties": False,
                "required": ["merge_jwt"],
                "properties": {
                    "email": {
                        "type": "object",
                        "nullable": True,
                        "default": None,
                        "example": None,
                        "additionalProperties": False,
                        "required": [
                            "original",
                            "merging",
                            "original_settings",
                            "merging_settings",
                        ],
                        "properties": {
                            "original": {
                                "type": "array",
                                "example": [
                                    {
                                        "email_address": "foo@example.com",
                                        "suppressed": False,
                                        "verified": True,
                                        "enabled": True,
                                    }
                                ],
                                "items": {
                                    "type": "object",
                                    "example": {
                                        "email_address": "foo@example.com",
                                        "suppressed": False,
                                        "verified": True,
                                        "enabled": True,
                                    },
                                    "additionalProperties": False,
                                    "required": [
                                        "email_address",
                                        "suppressed",
                                        "verified",
                                        "enabled",
                                    ],
                                    "properties": {
                                        "email_address": {
                                            "type": "string",
                                            "example": "foo@example.com",
                                        },
                                        "suppressed": {
                                            "type": "boolean",
                                            "example": False,
                                        },
                                        "verified": {
                                            "type": "boolean",
                                            "example": True,
                                        },
                                        "enabled": {"type": "boolean", "example": True},
                                    },
                                },
                            },
                            "merging": {
                                "type": "array",
                                "example": [
                                    {
                                        "email_address": "foo@example.com",
                                        "suppressed": False,
                                        "verified": True,
                                        "enabled": True,
                                    }
                                ],
                                "items": {
                                    "type": "object",
                                    "example": {
                                        "email_address": "foo@example.com",
                                        "suppressed": False,
                                        "verified": True,
                                        "enabled": True,
                                    },
                                    "additionalProperties": False,
                                    "required": [
                                        "email_address",
                                        "suppressed",
                                        "verified",
                                        "enabled",
                                    ],
                                    "properties": {
                                        "email_address": {
                                            "type": "string",
                                            "example": "foo@example.com",
                                        },
                                        "suppressed": {
                                            "type": "boolean",
                                            "example": False,
                                        },
                                        "verified": {
                                            "type": "boolean",
                                            "example": True,
                                        },
                                        "enabled": {"type": "boolean", "example": True},
                                    },
                                },
                            },
                            "original_settings": {
                                "type": "object",
                                "example": {
                                    "days_of_week": ["Monday"],
                                    "start_time": 21600,
                                    "end_time": 28800,
                                },
                                "additionalProperties": False,
                                "required": ["days_of_week", "start_time", "end_time"],
                                "properties": {
                                    "days_of_week": {
                                        "type": "array",
                                        "example": ["Monday"],
                                        "items": {
                                            "type": "string",
                                            "example": "Monday",
                                            "enum": [
                                                "Monday",
                                                "Tuesday",
                                                "Wednesday",
                                                "Thursday",
                                                "Friday",
                                                "Saturday",
                                                "Sunday",
                                            ],
                                        },
                                        "uniqueItems": True,
                                    },
                                    "start_time": {"type": "integer", "example": 21600},
                                    "end_time": {"type": "integer", "example": 28800},
                                },
                            },
                            "merging_settings": {
                                "type": "object",
                                "example": {
                                    "days_of_week": ["Monday"],
                                    "start_time": 21600,
                                    "end_time": 28800,
                                },
                                "additionalProperties": False,
                                "required": ["days_of_week", "start_time", "end_time"],
                                "properties": {
                                    "days_of_week": {
                                        "type": "array",
                                        "example": ["Monday"],
                                        "items": {
                                            "type": "string",
                                            "example": "Monday",
                                            "enum": [
                                                "Monday",
                                                "Tuesday",
                                                "Wednesday",
                                                "Thursday",
                                                "Friday",
                                                "Saturday",
                                                "Sunday",
                                            ],
                                        },
                                        "uniqueItems": True,
                                    },
                                    "start_time": {"type": "integer", "example": 21600},
                                    "end_time": {"type": "integer", "example": 28800},
                                },
                            },
                        },
                    },
                    "phone": {
                        "type": "object",
                        "nullable": True,
                        "default": None,
                        "example": None,
                        "additionalProperties": False,
                        "required": [
                            "original",
                            "merging",
                            "original_settings",
                            "merging_settings",
                        ],
                        "properties": {
                            "original": {
                                "type": "array",
                                "example": [
                                    {
                                        "phone_number": "+15555555551",
                                        "suppressed": False,
                                        "verified": True,
                                        "enabled": True,
                                    }
                                ],
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "required": [
                                        "phone_number",
                                        "suppressed",
                                        "verified",
                                        "enabled",
                                    ],
                                    "example": {
                                        "phone_number": "+15555555551",
                                        "suppressed": False,
                                        "verified": True,
                                        "enabled": True,
                                    },
                                    "properties": {
                                        "phone_number": {
                                            "type": "string",
                                            "example": "+15555555551",
                                        },
                                        "suppressed": {
                                            "type": "boolean",
                                            "example": False,
                                        },
                                        "verified": {
                                            "type": "boolean",
                                            "example": True,
                                        },
                                        "enabled": {"type": "boolean", "example": True},
                                    },
                                },
                            },
                            "merging": {
                                "type": "array",
                                "example": [
                                    {
                                        "phone_number": "+15555555552",
                                        "suppressed": False,
                                        "verified": True,
                                        "enabled": True,
                                    }
                                ],
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "example": {
                                        "phone_number": "+15555555551",
                                        "suppressed": False,
                                        "verified": True,
                                        "enabled": True,
                                    },
                                    "required": [
                                        "phone_number",
                                        "suppressed",
                                        "verified",
                                        "enabled",
                                    ],
                                    "properties": {
                                        "phone_number": {
                                            "type": "string",
                                            "example": "+15555555552",
                                        },
                                        "suppressed": {
                                            "type": "boolean",
                                            "example": False,
                                        },
                                        "verified": {
                                            "type": "boolean",
                                            "example": True,
                                        },
                                        "enabled": {"type": "boolean", "example": True},
                                    },
                                },
                            },
                            "original_settings": {
                                "type": "object",
                                "example": {
                                    "days_of_week": ["Monday"],
                                    "start_time": 21600,
                                    "end_time": 28800,
                                },
                                "additionalProperties": False,
                                "required": ["days_of_week", "start_time", "end_time"],
                                "properties": {
                                    "days_of_week": {
                                        "type": "array",
                                        "example": ["Monday"],
                                        "items": {
                                            "type": "string",
                                            "example": "Monday",
                                            "enum": [
                                                "Monday",
                                                "Tuesday",
                                                "Wednesday",
                                                "Thursday",
                                                "Friday",
                                                "Saturday",
                                                "Sunday",
                                            ],
                                        },
                                        "uniqueItems": True,
                                    },
                                    "start_time": {"type": "integer", "example": 21600},
                                    "end_time": {"type": "integer", "example": 28800},
                                },
                            },
                            "merging_settings": {
                                "type": "object",
                                "example": {
                                    "days_of_week": ["Monday"],
                                    "start_time": 21600,
                                    "end_time": 28800,
                                },
                                "additionalProperties": False,
                                "required": ["days_of_week", "start_time", "end_time"],
                                "properties": {
                                    "days_of_week": {
                                        "type": "array",
                                        "example": ["Monday"],
                                        "items": {
                                            "type": "string",
                                            "example": "Monday",
                                            "enum": [
                                                "Monday",
                                                "Tuesday",
                                                "Wednesday",
                                                "Thursday",
                                                "Friday",
                                                "Saturday",
                                                "Sunday",
                                            ],
                                        },
                                        "uniqueItems": True,
                                    },
                                    "start_time": {"type": "integer", "example": 21600},
                                    "end_time": {"type": "integer", "example": 28800},
                                },
                            },
                        },
                    },
                    "merge_jwt": {"type": "string", "example": "token"},
                },
            },
            "cta": {
                "type": "object",
                "example": {"text": "Merge"},
                "required": ["text"],
                "properties": {
                    "text": {
                        "type": "string",
                        "example": "Merge",
                        "description": "The text on the call to action button",
                    },
                    "trigger": {
                        "type": "string",
                        "format": "flow_slug",
                        "nullable": True,
                        "default": None,
                        "example": None,
                        "description": "The flow to trigger with no parameters after merging succeeds",
                    },
                    "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
                },
            },
            "skip": {
                "type": "object",
                "description": "Configures the secondary button that appears if an error occurs",
                "default": {"text": "Cancel Merge"},
                "example": {"text": "Cancel Merge"},
                "required": ["text"],
                "properties": {
                    "text": {
                        "type": "string",
                        "example": "Merge",
                        "description": "The text on the skip button",
                    },
                    "trigger": {
                        "type": "string",
                        "format": "flow_slug",
                        "nullable": True,
                        "default": None,
                        "example": None,
                        "description": "The flow to trigger with no parameters if the skip button is pressed",
                    },
                    "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
                },
            },
            "expired": {
                "type": "object",
                "nullable": True,
                "default": None,
                "example": {"trigger": "start_merge"},
                "description": "What to do if the merge JWT is expired",
                "properties": {
                    "trigger": {
                        "type": "string",
                        "format": "flow_slug",
                        "nullable": True,
                        "default": None,
                        "example": "start_merge",
                        "description": "The flow to trigger when the merge JWT is expired. This is triggered during a pop. Generally, should return to the start merge screen",
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
            "resolve_merge_conflict",
            "Resolve Merge Conflict",
            "Allows the user to resolve a merge conflict.",
            json.dumps(schema, sort_keys=True),
            int(
                ClientScreenFlag.SHOWS_IN_ADMIN
                | ClientScreenFlag.SHOWS_ON_ANDROID
                | ClientScreenFlag.SHOWS_ON_IOS
                | ClientScreenFlag.SHOWS_ON_BROWSER
            ),
        ),
    )
