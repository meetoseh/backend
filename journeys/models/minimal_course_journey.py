from pydantic import BaseModel, Field
from typing import Optional
from image_files.models import ImageFileRef
from journeys.models.minimal_journey import MinimalJourneyInstructor, MinimalJourney


class MinimalCourse(BaseModel):
    uid: str = Field(description="The unique identifier for the course")
    title: str = Field(description="The title of the of the course")


class MinimalCourseJourney(BaseModel):
    association_uid: str = Field(
        description=(
            "The unique identifier for the association between the course and the journey"
        )
    )
    course: MinimalCourse = Field(description="The course the journey belongs to")
    journey: MinimalJourney = Field(description="The actual journey within the course")
    priority: int = Field(
        description="Journeys with lower priority values are generally taken first"
    )
    joined_course_at: float = Field(
        description="When this user was added to this course"
    )
    is_next: bool = Field(
        description="True if this is the next journey to be taken in the course, false otherwise"
    )
