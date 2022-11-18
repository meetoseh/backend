from fastapi.responses import Response
from pydantic.generics import GenericModel
from pydantic import BaseModel, Field
from typing import Literal, TypeVar, Generic
from models import StandardErrorResponse, STANDARD_ERRORS_BY_CODE

EventTypeT = TypeVar("EventTypeT", bound=str)
EventDataT = TypeVar("EventDataT")


class NoJourneyEventData(BaseModel):
    """No data is required for this journey event type."""


class CreateJourneyEventRequest(GenericModel, Generic[EventDataT]):
    journey_uid: str = Field(
        description="The UID of the journey you are attempting to create an event in."
    )
    journey_jwt: str = Field(
        description=(
            "The JWT that proves you have permission to create an event in this journey. "
            "The Authorization header parameter should include the normal user credentials."
        )
    )
    session_uid: str = Field(
        description=(
            "The journey session for the user within which they are creating an event. A "
            "journey session refers to a single user's journey through a journey; a "
            "user can go through a journey multiple times, each with a different "
            "session."
        )
    )
    journey_time: float = Field(
        description=(
            "The offset in fracitonal seconds from the start of the journey when the "
            "event occurred."
        )
    )
    data: EventDataT = Field(
        description="Any additional data required to describe this event."
    )


class CreateJourneyEventResponse(GenericModel, Generic[EventTypeT, EventDataT]):
    uid: str = Field(description="The UID of the newly created event")
    user_sub: str = Field(description="The sub of the user who created the event")
    session_uid: str = Field(
        description="The UID of the session the event was created in"
    )
    type: EventTypeT = Field(description="The type of the event that was created")
    journey_time: float = Field(
        description=(
            "The journey time that the event was created at. "
            "This is the offset in fractional seconds from the start of the journey"
        ),
    )
    data: EventDataT = Field(
        description="Additional data required to describe the event, if any"
    )


CREATE_JOURNEY_EVENT_404_TYPES = Literal["not_found"]
"""Describes the possible error types for a 404 response to a create journey event request."""

CREATE_JOURNEY_EVENT_409_TYPES = Literal[
    "session_not_found",
    "session_not_started",
    "session_already_started",
    "session_already_ended",
    "session_has_later_event",
    "impossible_journey_time",
    "impossible_event",
    "impossible_event_data",
]
"""Describes the possible error types for a 409 response to a create journey event request."""

CREATE_JOURNEY_EVENT_STANDARD_ERRORS_BY_CODE = {
    "404": {
        "description": "There is no journey with that uid; it may have been deleted",
        "model": StandardErrorResponse[CREATE_JOURNEY_EVENT_404_TYPES],
    },
    "409": {
        "description": (
            "That journey exists but cannot receive events at this time, "
            "or the journey time is after the end of the journey, or the "
            "event type/data doesn't match the prompt (e.g., a numeric prompt "
            "response for a word prompt), or the journey session is not in a "
            "logical state for that event (e.g., attempting to like a journey "
            "with an already ended session, or the journey session is for "
            "a different journey)"
        ),
        "model": StandardErrorResponse[CREATE_JOURNEY_EVENT_409_TYPES],
    },
    **STANDARD_ERRORS_BY_CODE,
}
"""A valid value for responses in an api route - describes the standard error responses
that might be returned from a create journey event
"""

ERROR_JOURNEY_NOT_FOUND_RESPONSE = Response(
    content=StandardErrorResponse[CREATE_JOURNEY_EVENT_404_TYPES](
        type="not_found",
        message="There is no journey with that uid; it may have been deleted",
    ).json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=404,
)
"""The response to return when the journey for a journey event is not found. In practice
this should never happen because a journey JWT should only be issued to an existing journey,
but it's included for completeness."""

ERROR_JOURNEY_SESSION_NOT_FOUND_RESPONSE = Response(
    content=StandardErrorResponse[CREATE_JOURNEY_EVENT_409_TYPES](
        type="session_not_found",
        message="The specified journey session was not found or is for a different journey",
    ).json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=409,
)
"""The response to return when the journey session for a journey event is not found."""

ERROR_JOURNEY_SESSION_NOT_STARTED_RESPONSE = Response(
    content=StandardErrorResponse[CREATE_JOURNEY_EVENT_409_TYPES](
        type="session_not_started",
        message="The specified journey session has not been started yet",
    ).json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=409,
)
"""The response to return when the journey session for a journey event is not found."""

ERROR_JOURNEY_SESSION_ALREADY_STARTED_RESPONSE = Response(
    content=StandardErrorResponse[CREATE_JOURNEY_EVENT_409_TYPES](
        type="session_already_started",
        message="The specified journey session was already started (via a join event)",
    ).json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=409,
)
"""The response to return when the journey session for a journey event has already started, but
the the client tries to create a join event for it.
"""

ERROR_JOURNEY_SESSION_ALREADY_ENDED_RESPONSE = Response(
    content=StandardErrorResponse[CREATE_JOURNEY_EVENT_409_TYPES](
        type="session_already_ended",
        message="The specified journey session has already ended",
    ).json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=409,
)
"""The response to return when the journey session for a journey event has already ended."""

ERROR_JOURNEY_SESSION_HAS_LATER_EVENT_RESPONSE = Response(
    content=StandardErrorResponse[CREATE_JOURNEY_EVENT_409_TYPES](
        type="session_has_later_event",
        message="The specified journey session already has a journey event with a later journey_time",
    ).json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=409,
)
"""The response to return when the journey session already has a later journey event then the
one they are trying to save
"""

ERROR_JOURNEY_IMPOSSIBLE_JOURNEY_TIME_RESPONSE = Response(
    content=StandardErrorResponse[CREATE_JOURNEY_EVENT_409_TYPES](
        type="impossible_journey_time",
        message="The journey time is negative or after the end of the journey",
    ).json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=409,
)
"""The response to return when the journey time for a journey
event is negative or after the end of the journey. We cannot
enforce the journey time is positive using pydantic due to
https://github.com/pydantic/pydantic/issues/2581
"""
