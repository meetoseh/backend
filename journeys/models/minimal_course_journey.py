from typing import Optional
from pydantic import BaseModel, Field
from journeys.models.minimal_journey import MinimalJourney


class MinimalCourse(BaseModel):
    uid: str = Field(description="The unique identifier for the course")
    title: str = Field(description="The title of the of the course")
    liked_at: Optional[float] = Field(
        description="If the user liked the course, when in seconds since the epoch"
    )
    jwt: str = Field(description="A JWT with at least the VIEW_METADATA flag")


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
    joined_course_at: Optional[float] = Field(
        description="When this user was added to this course, if they were added at all"
    )
    is_next: bool = Field(
        description=(
            "True if the user is added to the course and this is the next journey "
            "to be taken in the course, false otherwise"
        )
    )
