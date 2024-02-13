from pydantic import BaseModel, Field
from image_files.models import ImageFileRef


class ExternalCourse(BaseModel):
    uid: str = Field(description="The primary stable external identifier")
    slug: str = Field(
        description="The chosen identifier for this course, for URLs or specific frontend behavior"
    )
    title: str = Field(description="The title of the course, used standalone")
    description: str = Field(description="A 250 character description for the course")
    background_image: ImageFileRef = Field(
        description="The background image for the course"
    )
