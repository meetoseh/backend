from aiohttp_retry import Optional
from pydantic import BaseModel, Field
from content_files.models import ContentFileRef
from image_files.models import ImageFileRef
from transcripts.models.transcript_ref import TranscriptRef


class ExternalCourseInstructor(BaseModel):
    uid: str = Field(
        description="The primary stable external identifier of the instructor"
    )
    name: str = Field(description="The name of the instructor")


class ExternalCourse(BaseModel):
    uid: str = Field(description="The primary stable external identifier")
    slug: str = Field(
        description="The chosen identifier for this course, for URLs or specific frontend behavior"
    )
    title: str = Field(description="The title of the course, used standalone")
    description: str = Field(description="The description of the course")
    instructor: ExternalCourseInstructor = Field(
        description="The instructor for the course"
    )
    background_image: ImageFileRef = Field(
        description="The background image for the course"
    )
    logo: Optional[ImageFileRef] = Field(
        description="The logo for the course, if available"
    )
    revenue_cat_entitlement: str = Field(
        description="The RevenueCat entitlement required for the course"
    )
    has_entitlement: bool = Field(
        description="Whether the user has entitlement to this course"
    )
    joined_at: Optional[float] = Field(
        description="If the user has joined the course, when they joined the course in seconds since the epoch"
    )
    liked_at: Optional[float] = Field(
        description="If the user has liked this course, when they liked this course in seconds since the epoch"
    )
    created_at: float = Field(
        description="When the course was created in seconds since the epoch"
    )
    num_journeys: int = Field(description="The number of journeys in the course")
    intro_video: Optional[ContentFileRef] = Field(
        description="The intro video for the course, if available"
    )
    intro_video_duration: Optional[float] = Field(
        description="The duration of the intro video for the course in seconds, if available"
    )
    intro_video_transcript: Optional[TranscriptRef] = Field(
        description="The intro video transcript for the course, if available"
    )
    intro_video_thumbnail: Optional[ImageFileRef] = Field(
        description="The intro video thumbnail/cover for the course, if available"
    )
    intro_video_thumbhash: Optional[str] = Field(
        description="The thumbhash of the intro thumbnail at a typical resolution, if available"
    )
