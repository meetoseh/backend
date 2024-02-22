from pydantic import BaseModel, Field
from typing import Optional

from image_files.models import ImageFileRef


class MinimalJourneyInstructor(BaseModel):
    name: str = Field(description="The full name of the instructor")
    image: Optional[ImageFileRef] = Field(
        description="The profile image for the instructor, if available"
    )


class MinimalJourney(BaseModel):
    """Contains minimal information about a journey and notably lacks a JWT
    to access the journey. Typically used where theres a dense listing of
    journeys, such as a users history.
    """

    uid: str = Field(description="The unique identifier for the journey")
    title: str = Field(description="The title of the of the journey")
    description: str = Field(description="The description of the journey")
    darkened_background: ImageFileRef = Field(
        description="The darkened background image for this journey"
    )
    duration_seconds: float = Field(
        description="The duration of the audio portion of the journey in seconds"
    )
    instructor: MinimalJourneyInstructor = Field(
        description="The instructor for the journey"
    )
    last_taken_at: Optional[float] = Field(
        description="The last time the user took the journey"
    )
    liked_at: Optional[float] = Field(description="When the user liked the journey")
