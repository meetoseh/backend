from typing import List, Optional
from pydantic import BaseModel, Field

from image_files.models import ImageFileRef
from image_files.auth import create_jwt as create_image_jwt
from dataclasses import dataclass
import json

from itgs import Itgs


class InternalHomeScreenImage(BaseModel):
    """Internal admin representation of a home screen image"""

    uid: str = Field(description="Primary stable external row identifier")
    image_file: ImageFileRef = Field(description="The original image")
    darkened_image_file: ImageFileRef = Field(description="The darkened image")
    start_time: float = Field(
        description="Minimum number of seconds from local midnight when the image can be shown"
    )
    end_time: float = Field(
        description="Maximum number of seconds from local midnight when the image can be shown"
    )
    flags: int = Field(
        description="A twos-complement 64-bit integer treated as a bitfield where each bit represents "
        "a different flag. True flags have no effect, but false flags prevent the image from being shown "
        "in the respective situation. Flag 1 is the least significant bit:\n"
        "1-7: VISIBLE_SUNDAY through VISIBLE_SATURDAY\n"
        "8-19: VISIBLE_JANUARY through VISIBLE_DECEMBER\n"
        "20: VISIBLE_WITHOUT_PRO\n"
        "21: VISIBLE_WITH_PRO\n"
        "22: VISIBLE_IN_ADMIN"
    )
    dates: Optional[List[str]] = Field(
        description="Either None, for no effect, or a list of dates in the format 'YYYY-MM-DD'. "
        "If not null, even if the list is empty, the image will not be displayed on any date not "
        "in this list. Intended for holiday images, e.g., Christmas, New Year's, etc."
    )
    created_at: float = Field(
        description="When this record was created in seconds since the epoch"
    )
    live_at: float = Field(
        description="This image cannot be shown earlier than this time in seconds since the unix epoch"
    )


@dataclass
class InternalHomeScreenImageRow:
    uid: str
    image_file_uid: str
    darkened_image_file_uid: str
    start_time: float
    end_time: float
    flags: int
    dates: Optional[str]
    created_at: float
    live_at: float


STANDARD_INTERNAL_HOME_SCREEN_IMAGE_ROW_SELECT_JOIN = """
SELECT
    home_screen_images.uid,
    original_image_files.uid,
    darkened_image_files.uid,
    home_screen_images.start_time,
    home_screen_images.end_time,
    home_screen_images.flags,
    home_screen_images.dates,
    home_screen_images.created_at,
    home_screen_images.live_at
FROM home_screen_images
JOIN image_files AS original_image_files ON home_screen_images.image_file_id = original_image_files.id
JOIN image_files AS darkened_image_files ON home_screen_images.darkened_image_file_id = darkened_image_files.id
"""


async def parse_internal_home_screen_image_row(
    itgs: Itgs, *, row: InternalHomeScreenImageRow
) -> InternalHomeScreenImage:
    """Parses a standard row returned from the database as the standard object"""
    return InternalHomeScreenImage(
        uid=row.uid,
        image_file=ImageFileRef(
            uid=row.image_file_uid, jwt=await create_image_jwt(itgs, row.image_file_uid)
        ),
        darkened_image_file=ImageFileRef(
            uid=row.darkened_image_file_uid,
            jwt=await create_image_jwt(itgs, row.darkened_image_file_uid),
        ),
        start_time=row.start_time,
        end_time=row.end_time,
        flags=row.flags,
        dates=None if row.dates is None else json.loads(row.dates),
        created_at=row.created_at,
        live_at=row.live_at,
    )
