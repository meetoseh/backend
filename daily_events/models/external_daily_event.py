from pydantic import BaseModel, Field
from typing import List


class ExternalDailyEventJourneyCategory(BaseModel):
    """A category as represented for the external-facing daily-events now endpoint"""

    external_name: str = Field(description="The name of the category, e.g., 'Verbal'")


class ExternalDailyEventJourneyInstructor(BaseModel):
    """An instructor as represented for the external-facing daily-events now endpoint"""

    name: str = Field(description="The name of the instructor")


class ExternalDailyEventJourneyDescription(BaseModel):
    """A description as represented for the external-facing daily-events now endpoint"""

    text: str = Field(description="The description text")


class ExternalDailyEventJourneyAccess(BaseModel):
    """Describes journey-related permissions"""

    start: bool = Field(
        description=(
            "True if the client can start this journey directly, using the daily "
            "event JWT returned, via the /daily_events/journeys/start "
            "endpoint"
        )
    )


class ExternalDailyEventJourney(BaseModel):
    """A representation for a journey as it's returned to end-users before they've
    chosen to start the journey, and potentially when they don't even have the
    option to start the journey.

    This endpoint is called by clients, meaning that breaking changes to its signature
    require a minimum of a 2 week turn-around, hence the seemingly excess objects. If
    we want to add e.g. an icon for journey categories, this allows it to be done
    reasonably concisely (result.category.icon) without breaking clients.
    """

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

    access: ExternalDailyEventJourneyAccess = Field(
        description="Indicates what permissions the client has with respect to this journey"
    )


class ExternalDailyEventAccess(BaseModel):
    """Describes event-related permissions"""

    start_random: bool = Field(
        description=(
            "True if the client can start a random journey within this event "
            "using the daily event JWT returned, via the "
            "/daily_events/journeys/start_random endpoint"
        )
    )


class ExternalDailyEvent(BaseModel):
    """Describes a daily event as exposed to end-users"""

    uid: str = Field(description="The UID of the daily event")

    jwt: str = Field(
        description="The JWT to use to access daily event client endpoints"
    )

    journeys: List[ExternalDailyEventJourney] = Field(
        description="The journeys which are part of this event", min_items=2
    )

    access: ExternalDailyEventAccess = Field(
        description="Indicates what broad permissions the client has with respect to this event"
    )
