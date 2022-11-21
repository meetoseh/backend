"""This module contains helper functions for endpoints that create journey
events.
"""
import time
from typing import Any, Callable, Dict, List, Literal, Optional, Generic, Tuple, TypeVar
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
from pypika import Query, Table, Parameter, Order, Tuple as SqlAliasable
from pypika.terms import Term, ExistsCriterion, ContainsCriterion
from pypika.queries import QueryBuilder


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
            "impossible_event",
            "impossible_event_data",
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
    bonus_terms: Optional[List[Tuple[Term, List[Any]]]] = None,
    bonus_error_checks: Optional[
        List[Tuple[Term, List[Any], Callable[[], CreateJourneyEventResult]]]
    ] = None,
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
        bonus_terms (list[tuple[Term, list[Any]]], None): If specified, these terms
            will be added to the where part of the INSERT statement. These terms will
            be able to reference `journey_sessions` which can be assumed to be
            for the correct journey session (with the user and journey already
            verified).

            Example:

    ```py
    journey_sessions = Table('journey_sessions')
    other_stuffs = Table('other_stuffs')
    bonus_terms = [
        (
            ExistsCriterion(
                Query.from_(other_stuffs)
                .select(1)
                .where(other_stuffs.journey_session_id == journey_sessions.id)
                .where(other_stuffs.uid == Parameter('?'))
            ),
            ['some-uid']
        )
    ]
    ```

            This would add the following to the where clause:

    ```sql
    EXISTS (
        SELECT 1 FROM "other_stuffs"
        WHERE "other_stuffs"."journey_session_id" = "journey_sessions"."id"
            AND "other_stuffs"."uid" = ?
    )
    ```

            and this will send the query parameter `some-uid` in the appropriate spot.
        bonus_error_checks (list[tuple[Term, list[Any], () -> CreateJourneyEventResult]], None):
            If specified, these are usually conceptually the same as the
            bonus_terms, but augmented to include a function that is called to
            produce the result of this function if the term fails, to improve
            the error response.

            Specifically, these terms will be inserted in the columns portion of
            a select after and only if the insert fails. The term must evaluate
            to a boolean, typically by being an ExistsCriterion. If the term
            evaluates to false, the function will be called to produce the
            result of this function.

            The bonus error checks will have the lower priority than the normal
            error checks, and will be checked in order. Thus, the bonus error
            checks can assume that, for example, the journey session exists and
            is for the correct user/journey.

            These terms will NOT be able to reference `journey_sessions`, though
            they can get that reference trivially with an exists criterion.

            Example:

    ```py
    journey_sessions = Table('journey_sessions')
    other_stuffs = Table('other_stuffs')
    bonus_error_checks = [
        (
            ExistsCriterion(
                Query.from_(other_stuffs)
                .select(1)
                .where(
                    ExistsCriterion(
                        Query.from_(journey_sessions)
                        .where(journey_sessions.id == other_stuffs.journey_session_id)
                        .where(journey_sessions.uid == Parameter('?'))
                    )
                )
                .where(other_stuffs.uid == Parameter('?'))
            ),
            [session_uid, 'some-uid']
        )
    ]
    ```

            This would add the following to the columns portion of the select:

    ```sql
    (
        EXISTS (
            SELECT 1 FROM "other_stuffs"
            WHERE
                EXISTS (
                    SELECT 1 FROM "journey_sessions"
                    WHERE "journey_sessions"."id" = "other_stuffs"."journey_session_id"
                        AND "journey_sessions"."uid" = ?
                )
                AND "other_stuffs"."uid" = ?
        )
    ) "b7"
    ```

            Note how the column alias is generated to a short unique value to reduce
            network traffic.

    Returns:
        CreateJourneyEventResult: The result of the operation
    """
    if journey_time < 0:
        return CreateJourneyEventResult(
            result=None,
            error_type="impossible_journey_time",
            error_response=ERROR_JOURNEY_IMPOSSIBLE_JOURNEY_TIME_RESPONSE,
        )

    event_uid = f"oseh_je_{secrets.token_urlsafe(16)}"
    serd_event_data = event_data.json()
    created_at = time.time()

    journey_events = Table("journey_events")
    journey_sessions = Table("journey_sessions")
    users = Table("users")
    journeys = Table("journeys")
    content_files = Table("content_files")
    journey_events_inner = journey_events.alias("je")

    query: QueryBuilder = (
        Query.into(journey_events)
        .columns(
            journey_events.uid,
            journey_events.journey_session_id,
            journey_events.evtype,
            journey_events.data,
            journey_events.journey_time,
            journey_events.created_at,
        )
        .select(
            Parameter("?"),
            journey_sessions.id,
            Parameter("?"),
            Parameter("?"),
            Parameter("?"),
            Parameter("?"),
        )
        .from_(journey_sessions)
        .where(journey_sessions.uid == Parameter("?"))
    )
    qargs = [
        event_uid,
        event_type,
        serd_event_data,
        journey_time,
        created_at,
        session_uid,
    ]

    session_is_for_user: Term = ExistsCriterion(
        Query.from_(users)
        .select(1)
        .where(users.id == journey_sessions.user_id)
        .where(users.sub == Parameter("?"))
    )
    session_is_for_user_qargs = [user_sub]

    query = query.where(session_is_for_user)
    qargs.extend(session_is_for_user_qargs)

    session_is_for_journey: Term = ExistsCriterion(
        Query.from_(journeys)
        .select(1)
        .where(journeys.id == journey_sessions.journey_id)
        .where(journeys.uid == Parameter("?"))
    )
    session_is_for_journey_qargs = [journey_uid]

    query = query.where(session_is_for_journey)
    qargs.extend(session_is_for_journey_qargs)

    journey_time_is_at_or_before_end: Term = ExistsCriterion(
        Query.from_(content_files)
        .select(1)
        .where(
            ExistsCriterion(
                Query.from_(journeys)
                .select(1)
                .where(journeys.id == journey_sessions.journey_id)
                .where(journeys.audio_content_file_id == content_files.id)
            )
        )
        .where(content_files.duration_seconds <= Parameter("?"))
    )
    journey_time_is_at_or_before_end_qargs = [journey_time]

    query = query.where(journey_time_is_at_or_before_end)
    qargs.extend(journey_time_is_at_or_before_end_qargs)

    session_has_event_term: Term = ExistsCriterion(
        Query.from_(journey_events_inner)
        .select(1)
        .where(journey_events_inner.journey_session_id == journey_sessions.id)
    )
    session_has_event_qargs = []

    if event_type == "join":
        query = query.where(~session_has_event_term)
    else:
        query = query.where(session_has_event_term)

    qargs.extend(session_has_event_qargs)

    session_is_finished_term: ContainsCriterion = Parameter("?").isin(
        Query.from_(journey_events_inner)
        .select(journey_events_inner.evtype)
        .where(journey_events_inner.journey_session_id == journey_sessions.id)
        .orderby(journey_events_inner.journey_time, order=Order.desc)
        .limit(1)
    )
    session_is_finished_qargs = ["leave"]

    query = query.where(session_is_finished_term.negate())
    qargs.extend(session_is_finished_qargs)

    session_has_later_event_term: Term = ExistsCriterion(
        Query.from_(journey_events_inner)
        .select(1)
        .where(journey_events_inner.journey_session_id == journey_sessions.id)
        .where(journey_events_inner.journey_time > Parameter("?"))
    )
    session_has_later_event_qargs = [journey_time]

    query = query.where(~session_has_later_event_term)
    qargs.extend(session_has_later_event_qargs)

    if bonus_terms:
        for term, term_qargs in bonus_terms:
            query = query.where(term)
            qargs.extend(term_qargs)

    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    response = await cursor.execute(query.get_sql(), qargs)
    if response.rows_affected is None or response.rows_affected < 1:

        def wrap_with_journey_sessions(
            term: Optional[Term], term_args: List[Any], *, is_strict: bool = True
        ) -> Tuple[Term, List[Any]]:
            result: QueryBuilder = (
                Query.from_(journey_sessions)
                .select(1)
                .where(journey_sessions.uid == Parameter("?"))
            )
            result_args = [session_uid]

            if is_strict:
                # whenever is_strict is false, it should behave the same as when
                # is_strict is true. we set is_strict to False when we've already
                # verified these parts, for simplicity of the query & for performance
                result = result.where(session_is_for_user)
                result_args.extend(session_is_for_user_qargs)

                result = result.where(session_is_for_journey)
                result_args.extend(session_is_for_journey_qargs)

            if term is not None:
                result = result.where(term)
                result_args.extend(term_args)

            return ExistsCriterion(result), [result_args]

        terms_and_args: List[
            Tuple[Term, List[Any], Callable[[], CreateJourneyEventResult]]
        ] = [
            (
                ExistsCriterion(
                    Query.from_(journeys)
                    .select(1)
                    .where(journeys.uid == Parameter("?"))
                ),
                [journey_uid],
                lambda: CreateJourneyEventResult(
                    result=None,
                    error_type="journey_not_found",
                    error_response=ERROR_JOURNEY_NOT_FOUND_RESPONSE,
                ),
            ),
            (
                *wrap_with_journey_sessions(None, []),
                lambda: CreateJourneyEventResult(
                    result=None,
                    error_type="session_not_found",
                    error_response=ERROR_JOURNEY_SESSION_NOT_FOUND_RESPONSE,
                ),
            ),
            (
                (
                    *wrap_with_journey_sessions(
                        session_has_event_term, session_has_event_qargs, is_strict=False
                    ),
                    lambda: CreateJourneyEventResult(
                        result=None,
                        error_type="session_not_started",
                        error_response=ERROR_JOURNEY_SESSION_NOT_STARTED_RESPONSE,
                    ),
                )
                if event_type != "join"
                else (
                    *wrap_with_journey_sessions(
                        ~session_has_event_term,
                        session_has_event_qargs,
                        is_strict=False,
                    ),
                    lambda: CreateJourneyEventResult(
                        result=None,
                        error_type="session_already_started",
                        error_response=ERROR_JOURNEY_SESSION_ALREADY_STARTED_RESPONSE,
                    ),
                )
            ),
            (
                *wrap_with_journey_sessions(
                    session_is_finished_term, session_is_finished_qargs, is_strict=False
                ),
                lambda: CreateJourneyEventResult(
                    result=None,
                    error_type="session_already_ended",
                    error_response=ERROR_JOURNEY_SESSION_ALREADY_ENDED_RESPONSE,
                ),
            ),
            (
                *wrap_with_journey_sessions(
                    session_has_later_event_term,
                    session_has_later_event_qargs,
                    is_strict=False,
                ),
                lambda: CreateJourneyEventResult(
                    result=None,
                    error_type="session_has_later_event",
                    error_response=ERROR_JOURNEY_SESSION_HAS_LATER_EVENT_RESPONSE,
                ),
            ),
        ]

        if bonus_error_checks:
            terms_and_args.extend(bonus_error_checks)

        query = Query.select()
        qargs = []
        for idx, (term, term_args, _) in enumerate(terms_and_args):
            query = query.select(SqlAliasable(term).as_(f"b{idx}"))
            qargs.extend(term_args)

        response = await cursor.execute(query.get_sql(), qargs)
        for success, (_, _, error_fn) in zip(response.results[0], terms_and_args):
            if not success:
                return error_fn()

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
