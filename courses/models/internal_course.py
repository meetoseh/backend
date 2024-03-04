from typing import Optional
from pydantic import BaseModel, Field
from content_files.models import ContentFileRef
from image_files.models import ImageFileRef


class InternalCourseInstructor(BaseModel):
    uid: str = Field(
        description="Primary stable external identifier for this instructor"
    )
    name: str = Field(description="The display name for this instructor")
    picture: Optional[ImageFileRef] = Field(
        description="The profile picture for this instructor"
    )


class InternalCourse(BaseModel):
    uid: str = Field(description="The primary stable external identifier")
    slug: str = Field(
        description="The chosen identifier for this course, for URLs or specific frontend behavior"
    )
    flags: int = Field(
        description="Access flags for this course as a twos-complement 64-bit integer"
    )
    revenue_cat_entitlement: str = Field(
        description="The name of the entitlement on revenuecat required for this course"
    )
    title: str = Field(description="The title of the course, used standalone")
    description: str = Field(description="A ~400 character description for the course")
    instructor: InternalCourseInstructor = Field(
        description="The instructor for this course"
    )
    background_original_image: Optional[ImageFileRef] = Field(
        description="The processed background image without any special filtering"
    )
    background_darkened_image: Optional[ImageFileRef] = Field(
        description="The processed background image with a darkening filter"
    )
    video_content: Optional[ContentFileRef] = Field(
        description="The introductory video for this course"
    )
    video_thumbnail: Optional[ImageFileRef] = Field(
        description="The preferred thumbnail for the introductory video"
    )
    logo_image: Optional[ImageFileRef] = Field(
        description="An image containing the rendered title with artistic flair"
    )
    hero_image: Optional[ImageFileRef] = Field(
        description="The hero image for the public share page"
    )
    created_at: float = Field(description="When the course was created")
