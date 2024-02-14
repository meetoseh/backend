from typing import Optional
from pydantic import BaseModel, Field
from image_files.models import ImageFileRef


class InternalCourse(BaseModel):
    uid: str = Field(description="The primary stable external identifier")
    slug: str = Field(
        description="The chosen identifier for this course, for URLs or specific frontend behavior"
    )
    revenue_cat_entitlement: str = Field(
        description="The name of the entitlement on revenuecat required for this course"
    )
    title: str = Field(description="The title of the course, used standalone")
    description: str = Field(description="A 250 character description for the course")
    background_image: Optional[ImageFileRef] = Field(
        description="The background image for the course, or None if using the default"
    )
    created_at: float = Field(description="When the course was created")
