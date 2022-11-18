"""This module contains helper functions for endpoints that create journey
events.
"""
import time
from typing import Any, Dict, Literal, Optional, Generic, TypeVar
from dataclasses import dataclass
from fastapi.responses import Response, JSONResponse
from pydantic import BaseModel, Field
from pydantic.generics import GenericModel
from itgs import Itgs
from journeys.events.models import (
    ERROR_JOURNEY_NOT_FOUND_RESPONSE,
    ERROR_JOURNEY_SESSION_ALREADY_ENDED_RESPONSE,
    ERROR_JOURNEY_SESSION_ALREADY_STARTED_RESPONSE,
    ERROR_JOURNEY_SESSION_HAS_LATER_EVENT_RESPONSE,
    ERROR_JOURNEY_SESSION_NOT_FOUND_RESPONSE,
    ERROR_JOURNEY_SESSION_NOT_STARTED_RESPONSE,
    CreateJourneyEventResponse,
    ERROR_JOURNEY_IMPOSSIBLE_JOURNEY_TIME_RESPONSE,
)
from models import StandardErrorResponse, ERROR_401_TYPE, ERROR_403_TYPE
import auth
import journeys.auth
import secrets


@dataclass
class SuccessfulAuthResult:
    user_sub: str
    """The sub of the user that was authenticated."""

    journey_uid: str
    """The UID of the journey which they have access too"""

    user_claims: Optional[Dict[str, Any]]
    """The claims of the user token, typically for debugging, if applicable for the token type"""

    journey_claims: Optional[Dict[str, Any]]
    """The claims of the journey token, typically for debugging, if applicable for the token type"""


@dataclass
class AuthResult:
    result: Optional[SuccessfulAuthResult]
    """if the authorization was successful, the information verified"""

    error_type: Optional[Literal["not_set", "bad_format", "invalid"]]
    """if the authorization failed, why it failed"""

    error_response: Optional[Response]
    """if the authorization failed, the suggested error response"""

    @property
    def success(self) -> bool:
        """True if it succeeded, False otherwise"""
        return self.result is not None


async def auth_create_journey_event(
    itgs: Itgs, *, authorization: Optional[str], journey_jwt: str, journey_uid: str
) -> AuthResult:
    """Performs the standard authorization for a create journey event, which
    involves both an authorization header (which user is performing the action)
    and a journey jwt (proof they are allowed to view/interact with the journey).

    Args:
        authorization (str, None): The value provided for the authorization header,
            or None if it was not provided.
        journey_jwt (str): The journey jwt provided in the request. Should not be
            prefixed with `bearer `
        journey_uid (str): The journey uid that the user specified. This is not
            really necessary for the backend, since it's in the jwt, but it ensures
            the client doesn't have a token mixup style bug.
    """
    if journey_jwt.startswith("bearer "):
        return AuthResult(
            result=None,
            error_type="bad_format",
            error_response=JSONResponse(
                content=StandardErrorResponse[ERROR_401_TYPE](
                    type="bad_format",
                    message=(
                        "The journey JWT should not be prefixed with `bearer ` when not sent "
                        "as a header parameter."
                    ),
                ).dict(),
                status_code=401,
            ),
        )

    journey_auth_result = await journeys.auth.auth_any(itgs, f"bearer {journey_jwt}")
    if not journey_auth_result.success:
        return AuthResult(
            result=None,
            error_type=journey_auth_result.error_type,
            error_response=journey_auth_result.error_response,
        )

    if journey_auth_result.result.journey_uid != journey_uid:
        return AuthResult(
            result=None,
            error_type="invalid",
            error_response=JSONResponse(
                content=StandardErrorResponse[ERROR_403_TYPE](
                    type="invalid",
                    message=(
                        "You are not authorized to perform this action on this journey. "
                        "The provided JWT is valid, but not for the indicated journey uid. "
                        "This is a token mix-up bug; to help debug, recall that the claims of the "
                        "JWT are not encrypted, and specifically the sub of the JWT should match "
                        "the journey uid. You can manually decode the JWT at jwt.io."
                    ),
                ).dict(),
                status_code=403,
            ),
        )

    user_auth_result = await auth.auth_any(itgs, authorization)
    if not user_auth_result.success:
        return AuthResult(
            result=None,
            error_type=user_auth_result.error_type,
            error_response=user_auth_result.error_response,
        )

    return AuthResult(
        result=SuccessfulAuthResult(
            user_sub=user_auth_result.result.sub,
            journey_uid=journey_auth_result.result.journey_uid,
            user_claims=user_auth_result.result.claims,
            journey_claims=journey_auth_result.result.claims,
        ),
        error_type=None,
        error_response=None,
    )


EventTypeT = TypeVar("EventTypeT", bound=str)
EventDataT = TypeVar("EventDataT", bound=BaseModel)


@dataclass
class CreateJourneyEventSuccessResult(Generic[EventTypeT, EventDataT]):
    """The information available when successfully creating a new journey event"""

    content: CreateJourneyEventResponse[EventTypeT, EventDataT]
    """The response content to return to the client"""

    created_at: float
    """The unix timestamp assigned to when the event was created."""

    @property
    def response(self) -> Response:
        """The response content wrapped in an actual response"""
        return Response(
            content=self.content.json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=201,
        )


@dataclass
class CreateJourneyEventResult(Generic[EventTypeT, EventDataT]):
    """The result of attempting to create a new journey event."""

    result: Optional[CreateJourneyEventSuccessResult]
    """If the event was successfully created, the result"""

    error_type: Optional[
        Literal[
            "not_found",
            "session_not_found",
            "session_not_started",
            "session_already_started",
            "session_already_ended",
            "session_has_later_event",
            "impossible_journey_time",
        ]
    ]
    """The reasons we might reject a request to create a new journey event,
    which aren't related to the event data. The event data should be validated
    prior to calling create_journey_event.
    """

    error_response: Optional[Response]
    """If the event was not successfully created, the response to return to the client"""

    @property
    def success(self) -> bool:
        """Convenience function to determine if the result was successful"""
        return self.result is not None


class JourneyEventPubSubMessage(GenericModel, Generic[EventTypeT, EventDataT]):
    """Describes a message that is published to the pubsub topic for a journey"""

    uid: str = Field(description="the uid of the new event")
    user_sub: str = Field(description="the uid of the user who created the event")
    session_uid: str = Field(
        description="the uid of the session the event was created in"
    )
    evtype: EventTypeT = Field(description="the type of the event")
    data: EventDataT = Field(description="the data of the event")
    journey_time: float = Field(description="the journey time of the event")
    created_at: float = Field(
        description="the unix timestamp of when the event was created"
    )


async def create_journey_event(
    itgs: Itgs,
    *,
    journey_uid: str,
    user_sub: str,
    session_uid: str,
    event_type: EventTypeT,
    event_data: EventDataT,
    journey_time: float,
) -> CreateJourneyEventResult[EventTypeT, EventDataT]:
    """Creates a new journey event for the given journey by the given user with
    the given type, data and journey time. This will assign a uid and created_at
    time to the event, and ensure it's persisted and propagated to listeners.

    Args:
        itgs (Itgs): The integrations for networked services
        journey_uid (str): The uid of the journey to create the event for
        user_sub (str): The sub of the user creating the event
        session_uid (str): The session uid of the user creating the event
        event_type (EventTypeT): The type of the event
        event_data (EventDataT): The data of the event
        journey_time (float): The journey time of the event

    Returns:
        CreateJourneyEventResult: The result of the operation
    """
    if journey_time < 0:
        return CreateJourneyEventResult(
            result=None,
            error_type="impossible_journey_time",
            error_response=ERROR_JOURNEY_IMPOSSIBLE_JOURNEY_TIME_RESPONSE,
        )

    conn = await itgs.conn()
    cursor = conn.cursor("strong")

    serd_event_data = event_data.json()

    event_uid = f"oseh_je_{secrets.token_urlsafe(16)}"
    created_at = time.time()
    response = await cursor.execute(
        """
        INSERT INTO journey_events (
            uid, journey_session_id, evtype, data,
            journey_time, created_at
        )
        SELECT
            ?, journey_sessions.id, ?, ?, ?, ?
        FROM journey_sessions
        WHERE
            journey_sessions.uid = ?
            AND EXISTS (
                SELECT 1 FROM users
                WHERE users.id = journey_sessions.user_id
                  AND users.uid = ?
            )
            AND EXISTS (
                SELECT 1 FROM journeys
                WHERE journeys.id = journey_sessions.journey_id
                  AND journeys.uid = ?
                  AND EXISTS (
                    SELECT 1 FROM content_files
                    WHERE content_files.id = journeys.audio_content_file_id
                      AND content_files.duration_seconds <= ?
                  )
            )
            AND (
                (? != ?) = EXISTS (
                    SELECT 1 FROM journey_events AS je
                    WHERE je.journey_session_id = journey_sessions.id
                )
            )
            AND ? NOT IN (
                SELECT je.evtype FROM journey_events AS je
                WHERE je.journey_session_id = journey_sessions.id
                ORDER BY je.journey_time DESC
                LIMIT 1
            )
            AND NOT EXISTS (
                SELECT 1 FROM journey_events AS je
                WHERE je.journey_session_id = journey_sessions.id
                  AND je.journey_time > ?
            )
        """,
        (
            event_uid,
            event_type,
            serd_event_data,
            journey_time,
            created_at,
            session_uid,
            user_sub,
            journey_uid,
            journey_time,
            event_type,
            "join",
            event_type,
            "leave",
        ),
    )
    if response.rows_affected is None or response.rows_affected < 1:
        response = await cursor.execute(
            """
            SELECT
                EXISTS (
                    SELECT 1 FROM journeys
                    WHERE uid=?
                ) AS b1,
                EXISTS (
                    SELECT 1 FROM journey_sessions
                    WHERE journey_sessions.uid = ?
                      AND EXISTS (
                        SELECT 1 FROM users
                        WHERE users.id = journey_sessions.user_id
                          AND users.sub = ?
                      )
                      AND EXISTS (
                        SELECT 1 FROM journeys
                        WHERE journeys.id = journey_sessions.journey_id
                          AND journeys.uid = ?
                      )
                ) AS b2,
                EXISTS (
                    SELECT 1 FROM journey_events
                    WHERE
                        EXISTS (
                            SELECT 1 FROM journey_sessions
                            WHERE journey_sessions.id = journey_events.journey_session_id
                              AND journey_sessions.uid = ?
                        )
                ) AS b3,
                (? IN (
                    SELECT evtype FROM journey_events
                    WHERE
                        EXISTS (
                            SELECT 1 FROM journey_sessions
                            WHERE journey_sessions.id = journey_events.journey_session_id
                              AND journey_sessions.uid = ?
                        )
                    ORDER BY journey_time DESC
                    LIMIT 1
                )) AS b4,
                EXISTS (
                    SELECT 1 FROM journey_events AS je
                    WHERE je.journey_session_id = journey_sessions.id
                    AND je.journey_time > ?
                ) AS b5
            """,
            (
                journey_uid,
                session_uid,
                user_sub,
                session_uid,
                "leave",
                session_uid,
                journey_time,
            ),
        )
        (
            journey_exists,
            session_exists,
            session_started,
            session_finished,
            later_event,
        ) = response.results[0]
        if not journey_exists:
            return CreateJourneyEventResult(
                result=None,
                error_type="journey_not_found",
                error_response=ERROR_JOURNEY_NOT_FOUND_RESPONSE,
            )
        if not session_exists:
            return CreateJourneyEventResult(
                result=None,
                error_type="session_not_found",
                error_response=ERROR_JOURNEY_SESSION_NOT_FOUND_RESPONSE,
            )
        if event_type != "join" and not session_started:
            return CreateJourneyEventResult(
                result=None,
                error_type="session_not_started",
                error_response=ERROR_JOURNEY_SESSION_NOT_STARTED_RESPONSE,
            )
        if event_type == "join" and session_started:
            return CreateJourneyEventResult(
                result=None,
                error_type="session_already_started",
                error_response=ERROR_JOURNEY_SESSION_ALREADY_STARTED_RESPONSE,
            )
        if session_finished:
            return CreateJourneyEventResult(
                result=None,
                error_type="session_already_ended",
                error_response=ERROR_JOURNEY_SESSION_ALREADY_ENDED_RESPONSE,
            )
        if later_event:
            return CreateJourneyEventResult(
                result=None,
                error_type="session_has_later_event",
                error_response=ERROR_JOURNEY_SESSION_HAS_LATER_EVENT_RESPONSE,
            )

        return CreateJourneyEventResult(
            result=None,
            error_type="impossible_journey_time",
            error_response=ERROR_JOURNEY_IMPOSSIBLE_JOURNEY_TIME_RESPONSE,
        )

    result = CreateJourneyEventResult(
        result=CreateJourneyEventSuccessResult(
            content=CreateJourneyEventResponse(
                uid=event_uid,
                user_sub=user_sub,
                type=event_type,
                journey_time=journey_time,
                data=event_data,
            ),
            created_at=created_at,
        ),
        error_type=None,
        error_response=None,
    )

    message = JourneyEventPubSubMessage(
        uid=event_uid,
        user_sub=user_sub,
        session_uid=session_uid,
        evtype=event_type,
        data=event_data,
        journey_time=journey_time,
        created_at=created_at,
    )

    redis = await itgs.redis()
    await redis.publish(
        f"ps:journeys:{journey_uid}:events".encode("utf-8"),
        message.json().encode("utf-8"),
    )

    return result
