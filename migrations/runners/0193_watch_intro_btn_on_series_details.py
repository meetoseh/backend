import json
from typing import cast
from itgs import Itgs
from lib.client_flows.helper import check_oas_30_schema
from lib.client_flows.screen_cache import purge_client_screen_cache
from migrations.shared.shared_screen_transition_002 import (
    SHARED_SCREEN_TRANSITION_SCHEMA_V002,
)


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    response = await cursor.execute(
        "SELECT uid FROM courses WHERE slug = ?", ("everyday-mindful",)
    )
    if response.results:
        default_course_uid = cast(str, response.results[0][0])
    else:
        response = await cursor.execute(
            "SELECT uid FROM courses WHERE EXISTS (SELECT 1 FROM course_journeys WHERE course_journeys.course_id = courses.id) ORDER BY slug ASC LIMIT 1"
        )
        if response.results:
            default_course_uid = cast(str, response.results[0][0])
        else:
            default_course_uid = "oseh_c_placeholder"

    schema = {
        "type": "object",
        "example": {"series": default_course_uid},
        "properties": {
            "series": {
                "type": "string",
                "format": "course_uid",
                "example": default_course_uid,
            },
            "entrance": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
            "buttons": {
                "type": "object",
                "example": {
                    "buy_now": {},
                    "back": {},
                    "take_class": {},
                },
                "default": {
                    "buy_now": {
                        "exit": {"type": "fade", "ms": 350},
                    },
                    "back": {
                        "exit": {"type": "fade", "ms": 350},
                    },
                    "take_class": {
                        "exit": {"type": "fade", "ms": 350},
                    },
                },
                "description": "What to do when the user the various interactibles",
                "properties": {
                    "buy_now": {
                        "type": "object",
                        "description": "If the course requires Oseh+ and the user doesn't have it, a purchase button is shown and this is used for when its pressed",
                        "example": {},
                        "default": {
                            "exit": {"type": "fade", "ms": 350},
                        },
                        "properties": {
                            "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
                            "trigger": {
                                "type": "string",
                                "format": "flow_slug",
                                "description": "This is triggered with the server parameter `series` set to a string (the uid of the series)",
                                "nullable": True,
                                "example": None,
                                "default": None,
                            },
                        },
                    },
                    "back": {
                        "type": "object",
                        "description": "The back button",
                        "example": {},
                        "default": {
                            "exit": {"type": "fade", "ms": 350},
                        },
                        "properties": {
                            "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
                            "trigger": {
                                "type": "string",
                                "format": "flow_slug",
                                "description": "Triggered without any parameters",
                                "nullable": True,
                                "example": None,
                                "default": None,
                            },
                        },
                    },
                    "take_class": {
                        "type": "object",
                        "description": "If the user owns the course, used when they tap one of the journeys. ",
                        "example": {},
                        "default": {
                            "exit": {"type": "fade", "ms": 350},
                        },
                        "properties": {
                            "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
                            "trigger": {
                                "type": "string",
                                "format": "flow_slug",
                                "description": "This is triggered with the server parameter `series` set to the uid of the series and `journey` set to the uid of the journey",
                                "nullable": True,
                                "example": None,
                                "default": None,
                            },
                        },
                    },
                    "rewatch_intro": {
                        "type": "object",
                        "nullable": True,
                        "description": "If not null, adds a button below the class list to rewatch the introduction video",
                        "example": {
                            "exit": {"type": "fade", "ms": 350},
                            "trigger": "view_series_list__preview",
                        },
                        "default": None,
                        "properties": {
                            "exit": SHARED_SCREEN_TRANSITION_SCHEMA_V002,
                            "trigger": {
                                "type": "string",
                                "format": "flow_slug",
                                "description": "This is triggered with the server parameter `series` set to the uid of the series",
                                "nullable": True,
                                "example": "view_series_list__preview",
                                "default": None,
                            },
                        },
                    },
                },
            },
        },
        "required": ["series"],
    }

    check_oas_30_schema(schema, require_example=True)

    await cursor.execute(
        """
UPDATE client_screens SET schema=? WHERE slug=?
        """,
        (
            json.dumps(schema, sort_keys=True),
            "series_details",
        ),
    )

    await purge_client_screen_cache(itgs, slug="series_details")
