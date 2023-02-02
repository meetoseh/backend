from pydantic import BaseModel, Field
from journeys.routes.read import Journey
from typing import Optional


class IntroductoryJourney(BaseModel):
    uid: str = Field(description="The primary stable unique identifier for this row")
    journey: Journey = Field(
        description="The journey that can be selected for users introducing themselves to the app"
    )
    user_sub: Optional[str] = Field(
        description="The sub of the user who marked the journey as introductory, if they haven't since been deleted"
    )
    created_at: float = Field(
        description="The time at which the row was created, in seconds since the epoch"
    )
