from pydantic import BaseModel, Field
from daily_events.models.external_daily_event import (
    ExternalDailyEventJourneyCategory,
    ExternalDailyEventJourneyDescription,
    ExternalDailyEventJourneyInstructor,
)
from image_files.models import ImageFileRef
from content_files.models import ContentFileRef
from journeys.models.prompt import Prompt


class ExternalJourney(BaseModel):
    """Describes a journey in the format we return it to clients with
    so that they can start the journey. They will typically exchange a
    daily event jwt for this response. This is different from the
    ExternalDailyEventJourney, which is used to _preview_ the journey,
    rather than actually start it
    """

    uid: str = Field(description="The UID of the journey")

    session_uid: str = Field(
        description="The UID of the new session within the journey, for event endpoints"
    )

    jwt: str = Field(description="The JWT which provides access to the journey")

    duration_seconds: float = Field(
        description="The duration of the journey, in seconds"
    )

    background_image: ImageFileRef = Field(
        description="The background image for the journey."
    )

    blurred_background_image: ImageFileRef = Field(
        description="The blurred background image for the journey."
    )

    audio_content: ContentFileRef = Field(
        description="The audio content for the journey"
    )

    category: ExternalDailyEventJourneyCategory = Field(
        description="How the journey is categorized"
    )

    title: str = Field(description="The very short class title")

    instructor: ExternalDailyEventJourneyInstructor = Field(
        description="The instructor for the journey"
    )

    description: ExternalDailyEventJourneyDescription = Field(
        description="The description of the journey"
    )

    prompt: Prompt = Field(description="The prompt for the journey")
