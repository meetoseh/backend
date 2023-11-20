from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal, Optional, TypeVar, Generic
from image_files.models import ImageFileRef
from models import StandardErrorResponse, STANDARD_ERRORS_BY_CODE

EventTypeT = TypeVar("EventTypeT", bound=str)
EventDataT = TypeVar("EventDataT")


class NoInteractivePromptEventData(BaseModel):
    """No data is required for this interactive prompt event type."""


class NameEventData(BaseModel):
    """The users name is required for this interactive prompt event type"""

    name: str = Field(
        description="The name of the user, potentially just the given/preferred name"
    )


class CreateInteractivePromptEventRequest(BaseModel, Generic[EventDataT]):
    interactive_prompt_uid: str = Field(
        description="The UID of the interactive prompt you are attempting to create an event in."
    )
    interactive_prompt_jwt: str = Field(
        description=(
            "The JWT that proves you have permission to create an event in this prompt. "
            "The Authorization header parameter should include the normal user credentials."
        )
    )
    session_uid: str = Field(
        description=(
            "The interactive prompt session for the user within which they are creating an event. A "
            "interactive prompt session refers to a single user's progress through a prompt; a "
            "user can go through an interactive prompt multiple times, each with a different "
            "session."
        )
    )
    prompt_time: float = Field(
        description=(
            "The offset in fracitonal seconds from the start of the interactive prompt "
            "when the event occurred."
        )
    )
    data: EventDataT = Field(
        description="Any additional data required to describe this event."
    )


class CreateInteractivePromptEventResponse(BaseModel, Generic[EventTypeT, EventDataT]):
    uid: str = Field(description="The UID of the newly created event")
    user_sub: str = Field(description="The sub of the user who created the event")
    session_uid: str = Field(
        description="The UID of the session the event was created in"
    )
    type: EventTypeT = Field(description="The type of the event that was created")
    prompt_time: float = Field(
        description=(
            "The prompt time that the event was created at. "
            "This is the offset in fractional seconds from the start of the prompt"
        ),
    )
    icon: Optional[ImageFileRef] = Field(
        description=(
            "If an icon is associated with this event, a reference to the corresponding "
            "image file."
        )
    )
    data: EventDataT = Field(
        description="Additional data required to describe the event, if any"
    )


CREATE_INTERACTIVE_PROMPT_EVENT_404_TYPES = Literal["not_found"]
"""Describes the possible error types for a 404 response to a create interactive prompt event request."""

CREATE_INTERACTIVE_PROMPT_EVENT_409_TYPES = Literal[
    "session_not_found",
    "session_not_started",
    "session_already_started",
    "session_already_ended",
    "session_has_later_event",
    "session_has_same_event_at_same_time",
    "impossible_prompt_time",
    "impossible_event",
    "impossible_event_data",
]
"""Describes the possible error types for a 409 response to a create prompt event request."""

CREATE_INTERACTIVE_PROMPT_EVENT_STANDARD_ERRORS_BY_CODE = {
    "404": {
        "description": "There is no interactive prompt with that uid; it may have been deleted",
        "model": StandardErrorResponse[CREATE_INTERACTIVE_PROMPT_EVENT_404_TYPES],
    },
    "409": {
        "description": (
            "That prompt exists but cannot receive events at this time, "
            "or the prompt time is after the end of the prompt, or the "
            "event type/data doesn't match the prompt (e.g., a numeric prompt "
            "response for a word prompt), or the prompt session is not in a "
            "logical state for that event (e.g., attempting to like a prompt "
            "with an already ended session, or the prompt session is for "
            "a different prompt)"
        ),
        "model": StandardErrorResponse[CREATE_INTERACTIVE_PROMPT_EVENT_409_TYPES],
    },
    **STANDARD_ERRORS_BY_CODE,
}
"""A valid value for responses in an api route - describes the standard error responses
that might be returned from a create interactive prompt event endpoint
"""

ERROR_INTERACTIVE_PROMPT_NOT_FOUND_RESPONSE = Response(
    content=StandardErrorResponse[CREATE_INTERACTIVE_PROMPT_EVENT_404_TYPES](
        type="not_found",
        message="There is no interactive prompt with that uid; it may have been deleted",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=404,
)
"""The response to return when the interactive prompt for a prompt event is not
found. In practice this should never happen because an interactive prompt JWT
should only be issued to an existing interactive prompt, but it's included for
completeness.
"""

ERROR_INTERACTIVE_PROMPT_SESSION_NOT_FOUND_RESPONSE = Response(
    content=StandardErrorResponse[CREATE_INTERACTIVE_PROMPT_EVENT_409_TYPES](
        type="session_not_found",
        message="The specified interactive prompt session was not found or is for a different prompt",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=409,
)
"""The response to return when the interactive prompt session for a prompt event is not found."""

ERROR_INTERACTIVE_PROMPT_SESSION_NOT_STARTED_RESPONSE = Response(
    content=StandardErrorResponse[CREATE_INTERACTIVE_PROMPT_EVENT_409_TYPES](
        type="session_not_started",
        message="The specified interactive prompt session has not been started yet",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=409,
)
"""The response to return when the interactive prompt session for a prompt event is not found."""

ERROR_INTERACTIVE_PROMPT_SESSION_ALREADY_STARTED_RESPONSE = Response(
    content=StandardErrorResponse[CREATE_INTERACTIVE_PROMPT_EVENT_409_TYPES](
        type="session_already_started",
        message="The specified interactive prompt session was already started (via a join event)",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=409,
)
"""The response to return when the interactive prompt session for a interactive
prompt event has already started, but the the client tries to create a join
event for it.
"""

ERROR_INTERACTIVE_PROMPT_SESSION_ALREADY_ENDED_RESPONSE = Response(
    content=StandardErrorResponse[CREATE_INTERACTIVE_PROMPT_EVENT_409_TYPES](
        type="session_already_ended",
        message="The specified interactive prompt session has already ended",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=409,
)
"""The response to return when the interactive prompt session for a prompt event has already ended."""

ERROR_INTERACTIVE_PROMPT_SESSION_HAS_LATER_EVENT_RESPONSE = Response(
    content=StandardErrorResponse[CREATE_INTERACTIVE_PROMPT_EVENT_409_TYPES](
        type="session_has_later_event",
        message="The specified interactive prompt session already has an event with a later prompt_time",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=409,
)
"""
The response to return when the interactive prompt session already has a later
prompt event then the one they are trying to save
"""

ERROR_INTERACTIVE_PROMPT_SESSION_HAS_SAME_EVENT_AT_SAME_TIME_RESPONSE = Response(
    content=StandardErrorResponse[CREATE_INTERACTIVE_PROMPT_EVENT_409_TYPES](
        type="session_has_same_event_at_same_time",
        message="The specified interactive prompt session already has an event with the same type with the same prompt_time",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=409,
)
"""The response to return when the interactive prompt session already has an event
with the same type and prompt time as the one they are trying to save. Having
multiple events with the same type and time results in difficulty in matching
events, so this is not allowed.
"""

ERROR_INTERACTIVE_PROMPT_IMPOSSIBLE_PROMPT_TIME_RESPONSE = Response(
    content=StandardErrorResponse[CREATE_INTERACTIVE_PROMPT_EVENT_409_TYPES](
        type="impossible_prompt_time",
        message="The prompt time is negative or after the end of the interactive portion of the prompt",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=409,
)
"""The response to return when the prompt time for a prompt
event is negative or after the end of the prompt time. We cannot
enforce the prompt time is positive using pydantic due to
https://github.com/pydantic/pydantic/issues/2581
"""
