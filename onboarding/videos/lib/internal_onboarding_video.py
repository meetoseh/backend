from typing import Annotated, Literal, Optional, Union
from pydantic import BaseModel, Field, StringConstraints, TypeAdapter
from dataclasses import dataclass

from content_files.models import ContentFileRef
from content_files.auth import create_jwt as create_content_file_jwt
from image_files.models import ImageFileRef
from image_files.auth import create_jwt as create_image_file_jwt
from itgs import Itgs


class OVPurposeWelcome(BaseModel):
    type: Literal["welcome"] = Field(
        description="Discriminatory field; indicates this is for the first video after the user logs in"
    )
    language: Annotated[
        str, StringConstraints(min_length=2, max_length=2, to_lower=True)
    ] = Field(
        description="ISO 639-1 two-letter individual language code, e.g., 'en' for english",
        examples=["en", "es", "fr", "de", "it", "ja", "ko", "pt", "ru", "zh"],
    )
    voice: Literal["male", "female", "ambiguous", "multiple"] = Field(
        description=(
            "The apparent gender of the voiceover, or ambiguous if it is "
            "not clear from the audio, or multiple if there are multiple "
            "speakers with different apparent genders"
        )
    )


# Only 1 right now
OnboardingVideoPurpose = OVPurposeWelcome
onboarding_video_purpose_adapter: TypeAdapter[OnboardingVideoPurpose] = TypeAdapter(
    OnboardingVideoPurpose
)


class InternalOnboardingVideo(BaseModel):
    uid: str = Field(description="Primary stable external row identifier")
    purpose: OnboardingVideoPurpose = Field(
        description=(
            "The purpose of the video. There is only one active "
            "onboarding video per purpose"
        )
    )
    video_content: ContentFileRef = Field(description="The actual video file")
    thumbnail_image: ImageFileRef = Field(
        description="The thumbnail/cover image for the video"
    )
    active_at: Optional[float] = Field(
        description=(
            "Null unless this is the active video for the purpose, in which "
            "case when it was marked active in seconds since the epoch"
        )
    )
    visible_in_admin: bool = Field(
        description="Whether this video is visible in the admin interface by default"
    )
    created_at: float = Field(
        description="When this video was created in seconds since the epoch"
    )


STANDARD_INTERNAL_ONBOARDING_VIDEO_ROW_SELECT_JOIN = """
SELECT
    onboarding_videos.uid,
    onboarding_videos.purpose,
    content_files.uid,
    image_files.uid,
    onboarding_videos.active_at,
    onboarding_videos.visible_in_admin,
    onboarding_videos.created_at
FROM onboarding_videos
JOIN content_files ON content_files.id = onboarding_videos.video_content_file_id
JOIN image_files ON image_files.id = onboarding_videos.thumbnail_image_file_id
"""


@dataclass
class InternalOnboardingVideoRow:
    """The raw row returned from the standard query"""

    uid: str
    purpose: str
    video_content_file_uid: str
    thumbnail_image_file_id: str
    active_at: Optional[float]
    visible_in_admin: Union[Literal[0, 1], bool]
    created_at: float


async def parse_internal_onboarding_video_row(
    itgs: Itgs, *, row: InternalOnboardingVideoRow
) -> InternalOnboardingVideo:
    """Parses a row as if from the standard select query into the
    typed representation
    """
    return InternalOnboardingVideo(
        uid=row.uid,
        purpose=onboarding_video_purpose_adapter.validate_json(row.purpose),
        video_content=ContentFileRef(
            uid=row.video_content_file_uid,
            jwt=await create_content_file_jwt(itgs, row.video_content_file_uid),
        ),
        thumbnail_image=ImageFileRef(
            uid=row.thumbnail_image_file_id,
            jwt=await create_image_file_jwt(itgs, row.thumbnail_image_file_id),
        ),
        active_at=row.active_at,
        visible_in_admin=bool(row.visible_in_admin),
        created_at=row.created_at,
    )
