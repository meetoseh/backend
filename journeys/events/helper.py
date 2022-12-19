"""This module contains helper functions for endpoints that create journey
events.
"""
import json
import time
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Literal,
    NoReturn,
    Optional,
    Generic,
    Tuple,
    TypeVar,
    Union,
)
from dataclasses import dataclass
from fastapi.responses import Response, JSONResponse
from pydantic import BaseModel, Field, validator
from pydantic.generics import GenericModel
from itgs import Itgs
from journeys.events.models import (
    ERROR_JOURNEY_NOT_FOUND_RESPONSE,
    ERROR_JOURNEY_SESSION_ALREADY_ENDED_RESPONSE,
    ERROR_JOURNEY_SESSION_ALREADY_STARTED_RESPONSE,
    ERROR_JOURNEY_SESSION_HAS_LATER_EVENT_RESPONSE,
    ERROR_JOURNEY_SESSION_HAS_SAME_EVENT_AT_SAME_TIME_RESPONSE,
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
import perpetual_pub_sub as pps
import math
import re


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


class CachedJourneyMeta(BaseModel):
    """Describes cached meta information for a journey"""

    uid: str = Field(description="the uid of the journey")
    duration_seconds: float = Field(
        description="the duration of the journey in seconds"
    )
    bins: int = Field(description="the number of bins in the fenwick trees", ge=1)
    prompt: Dict[str, Any] = Field(description="the prompt information for the journey")

    @validator("bins")
    def bins_is_one_less_than_pow2(cls, v):
        if v & (v + 1) != 0:
            raise ValueError(f"bins must be one less than a power of 2 (got {v})")
        return v


@dataclass
class PrefixSumUpdate:
    """Describes an update to a fenwick tree that needs to be performed
    as a result of a new event. This is intended to be created before
    accessing the database, and hence this may describe the conditions
    for an update rather than the updates themselves.

    A simple update would be the fenwick tree for the number of likes.
    Whenever a user likes an event, the number of likes goes up. This
    type of update can be entirely described without accessing the
    database.

    A more complex update would be the number of active numeric responses
    with a particular rating. It always involves an increment for the new
    rating, but it may require a decrement based on the sessions previous
    rating (if there was one). Thus the actual values to update cannot be
    enumerated prior to the transaction.

    The entire update will be sent within a transaction without waiting
    for any selects to return. The general idea is that, in sql, we will
    convert this into

    - increment the new rating at the journey time
    - decrement the old rating at the journey time

    focusing on the second part, that becomes

    ```txt
    decrement from each rating at the journey time
    where there exists a previous event
        within the same session
        with that rating
        without a later numeric response
    ```

    note that it would seem as if we could always use an update for
    the decrement operation, however, it's possible that we decrement
    a previously uninitialized value:

    consider the fenwick tree with 7 bins, and 1 event at bin 1 (1-indexed)

    ```txt
    {
        1: 1
        1...2: 1
        3: 0 (uninitialized)
        1...4: 1
        5: 0 (uninitialized)
        5...6: 0 (uninitialized)
        7: 0 (uninitialized)
    }
    ```

    If we need to decrement at 3, the new fenwick tree becomes

    ```txt
    {
        1: 1,
        1...2: 1,
        3: -1,
        1...4: 0,
        5: 0 (uninitialized),
        5...6: 0 (uninitialized),
        7: 0 (uninitialized)
    }
    ```

    here we had to initialize the value at 3. Thus both the increment and
    decrement will be an upsert operation. Here's what that upsert generally
    looks like, with a few simplifications:

    ```sql
    INSERT INTO journey_event_fenwick_trees (
        journey_id, category, category_value, idx, val
    )
    SELECT
        journeys.id,
        ?,  /* category */
        ?,  /* category value; m values to consider */
        ?,  /* idx to update; at most log(n) values will need updating */
        ?   /* the amount to initialize at, only used if the row doesn't exist */
    FROM journeys
    WHERE
        journeys.uid = ? /* uid of the journey */
        /* verifies our event was actually inserted to avoid duplicating sanity checks */
        AND EXISTS (
            SELECT 1 FROM journey_events
            WHERE journey_events.uid = ? /* the event uid we're trying to insert */
        )
        AND (
            /* this would be the condition */
            1=1
        )
    ON CONFLICT (journey_id, category, category_value, idx)
    DO UPDATE SET val = val + ? /* the amount to add, this will only be used if the row exists */
    ```

    The indices to update can be merged into a single query using
    the following trick:

    ```
    WITH indices(idx) AS (VALUES (?), (?))
    SELECT * from indices
    ```

    which gives two rows.

    For the decrement upsert, we can simplify the query if we find the last
    event in the session with the type and use that for the category value,
    rather than enumerating the category values.
    """

    category: str
    """The category of tree being updated, e.g., likes. The categories are
    enumerated in the journey_event_fenwick_trees database docs
    """

    amount: int
    """The amount to change the tree by, typically either +1 or -1"""

    simple: bool
    """Whether this is a simple upsert, meaning that we are updating exactly
    one category value and we can determine which one in advance.
    """

    category_value: Optional[int]
    """Only relevant is simple is True. The category value to update, which may
    be null (e.g., the `like` category has no category value).

    If simple is False, this value is ignored, since the category value presumably
    can't be determined without looking at an earlier event.
    """

    event_type: Optional[str]
    """Only relevant if simple is False. The earlier event type that we are
    looking for to determine which category value to update. For example, if the
    category is `numeric_active`, this would be `numeric_prompt_response`.

    If simple is True, this value is ignored.
    """

    event_data_field: Optional[str]
    """Only relevant if simple is False. This is the field in the journey_events
    data which contains the category value. For example, if the category is
    `numeric_active`, this would be `rating`, since for `numeric_prompt_response`
    the journey event data contains a `rating` field.

    If simple is True, this value is ignored.
    """

    def to_queries(
        self,
        *,
        journey_event_uid: str,
        journey_time: int,
        journey_meta: CachedJourneyMeta,
    ) -> List[Tuple[str, List[Any]]]:
        """Produces the required sql queries to update the fenwick tree described
        by this prefix sum update.

        Args:
            journey_event_uid (str): The UID of the journey event being inserted. The
                fenwick tree is only updated if this event is actually inserted.
            journey_time (float): The journey time of the journey event being inserted.
            journey_meta (CachedJourneyMeta): Cached meta information about the
                journey, required to determine what queries are required. This only
                contains immutable information about the journey and does not effect
                the atomicity of the queries.

        Returns:
            The queries to execute, in the form of (query, params) tuples.
        """
        bin_width = journey_meta.duration_seconds / journey_meta.bins
        bin_idx = min(max(0, int(journey_time / bin_width)), journey_meta.bins - 1)

        indices = []
        one_based_idx = bin_idx + 1
        while one_based_idx <= journey_meta.bins:
            indices.append(one_based_idx - 1)
            one_based_idx += one_based_idx & -one_based_idx

        qmark_list = ", ".join(["(?)"] * len(indices))

        if self.simple:
            conflict_key = (
                "(journey_id, category, category_value, idx)"
                if self.category_value is not None
                else "(journey_id, category, idx) WHERE category_value IS NULL"
            )
            return [
                (
                    re.sub(
                        "\s+",
                        " ",
                        f"""
                        WITH indices(idx) AS (VALUES {qmark_list})
                        INSERT INTO journey_event_fenwick_trees (
                            journey_id, category, category_value, idx, val
                        )
                        SELECT
                            journeys.id, ?, ?, indices.idx, ?
                        FROM journeys, indices
                        WHERE
                            journeys.uid = ?
                            AND EXISTS (SELECT 1 FROM journey_events WHERE journey_events.uid=?)
                        ON CONFLICT {conflict_key}
                        DO UPDATE SET val = val + ?
                        """,
                    ).strip(),
                    (
                        *indices,
                        self.category,
                        self.category_value,
                        self.amount,
                        journey_meta.uid,
                        journey_event_uid,
                        self.amount,
                    ),
                )
            ]

        return [
            (
                re.sub(
                    "\s+",
                    " ",
                    f"""
                    WITH indices(idx) AS (VALUES {qmark_list})
                    INSERT INTO journey_event_fenwick_trees (
                        journey_id, category, category_value, idx, val
                    )
                    SELECT
                        journeys.id, ?, json_extract(journey_events.data, ?), indices.idx, ?
                    FROM journeys, indices, journey_events
                    WHERE
                        journeys.uid = ?
                        AND journey_events.uid != ?
                        AND EXISTS (
                            SELECT 1 FROM journey_events AS je
                            WHERE je.journey_session_id = journey_events.journey_session_id
                              AND je.uid = ?
                        )
                        AND journey_events.evtype = ?
                        AND NOT EXISTS (
                            SELECT 1 FROM journey_events AS je
                            WHERE je.journey_session_id = journey_events.journey_session_id
                              AND je.evtype = ?
                              AND je.journey_time > journey_events.journey_time
                              AND je.uid != ?
                        )
                    ON CONFLICT (journey_id, category, category_value, idx)
                    DO UPDATE SET val = val + ?
                    ON CONFLICT (journey_id, category, idx) WHERE category_value IS NULL
                    DO UPDATE SET val = val + ?
                    """,
                ).strip(),
                (
                    *indices,
                    self.category,
                    f"$.{self.event_data_field}",
                    self.amount,
                    journey_meta.uid,
                    journey_event_uid,
                    journey_event_uid,
                    self.event_type,
                    self.event_type,
                    journey_event_uid,
                    self.amount,
                    self.amount,
                ),
            )
        ]


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
    prefix_sum_updates: Optional[List[PrefixSumUpdate]] = None,
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

        prefix_sum_updates (list[PrefixSumUpdate], None): If specified, these
            prefix sum updates will be performed iff the journey event is
            stored. This is required for keeping the stats endpoint up to date.
            See PrefixSumUpdate for more details.

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
    journey_events_inner = journey_events.as_("je")

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
        .where(content_files.duration_seconds >= Parameter("?"))
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

    session_has_same_event_type_at_same_time_term: Term = ExistsCriterion(
        Query.from_(journey_events_inner)
        .select(1)
        .where(journey_events_inner.journey_session_id == journey_sessions.id)
        .where(journey_events_inner.journey_time == Parameter("?"))
        .where(journey_events_inner.evtype == Parameter("?"))
    )
    session_has_same_event_type_at_same_time_qargs = [journey_time, event_type]

    query = query.where(~session_has_same_event_type_at_same_time_term)
    qargs.extend(session_has_same_event_type_at_same_time_qargs)

    if bonus_terms:
        for term, term_qargs in bonus_terms:
            query = query.where(term)
            qargs.extend(term_qargs)

    queries: List[Tuple[str, List[Any]]] = [(query.get_sql(), qargs)]

    queries.append(
        (
            "INSERT INTO journey_event_counts "
            "(journey_id, bucket, total) "
            "SELECT journeys.id, ?, 1 "
            "FROM journeys "
            "WHERE"
            " journeys.uid = ?"
            " AND EXISTS (SELECT 1 FROM journey_events WHERE journey_events.uid = ?) "
            "ON CONFLICT (journey_id, bucket) DO UPDATE SET total = journey_event_counts.total + 1",
            (int(journey_time), journey_uid, event_uid),
        )
    )

    journey_meta = await get_journey_meta(itgs, journey_uid)
    if journey_time > journey_meta.duration_seconds:
        return CreateJourneyEventResult(
            result=None,
            error_type="impossible_journey_time",
            error_response=ERROR_JOURNEY_IMPOSSIBLE_JOURNEY_TIME_RESPONSE,
        )

    if journey_meta is None:
        return CreateJourneyEventResult(
            result=None,
            error_type="journey_not_found",
            error_response=ERROR_JOURNEY_NOT_FOUND_RESPONSE,
        )

    for update in prefix_sum_updates or []:
        queries.extend(
            update.to_queries(
                journey_event_uid=event_uid,
                journey_time=journey_time,
                journey_meta=journey_meta,
            )
        )

    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    response = (await cursor.executemany3(queries))[0]
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

            return ExistsCriterion(result), result_args

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
                    ~session_is_finished_term,
                    session_is_finished_qargs,
                    is_strict=False,
                ),
                lambda: CreateJourneyEventResult(
                    result=None,
                    error_type="session_already_ended",
                    error_response=ERROR_JOURNEY_SESSION_ALREADY_ENDED_RESPONSE,
                ),
            ),
            (
                *wrap_with_journey_sessions(
                    ~session_has_later_event_term,
                    session_has_later_event_qargs,
                    is_strict=False,
                ),
                lambda: CreateJourneyEventResult(
                    result=None,
                    error_type="session_has_later_event",
                    error_response=ERROR_JOURNEY_SESSION_HAS_LATER_EVENT_RESPONSE,
                ),
            ),
            (
                *wrap_with_journey_sessions(
                    ~session_has_same_event_type_at_same_time_term,
                    session_has_same_event_type_at_same_time_qargs,
                    is_strict=False,
                ),
                lambda: CreateJourneyEventResult(
                    result=None,
                    error_type="session_has_same_event_at_same_time",
                    error_response=ERROR_JOURNEY_SESSION_HAS_SAME_EVENT_AT_SAME_TIME_RESPONSE,
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
                session_uid=session_uid,
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


async def get_cached_journey_meta(
    itgs: Itgs, journey_uid: str
) -> Optional[CachedJourneyMeta]:
    """Gets the cached journey meta information, if it's already cached"""
    local_cache = await itgs.local_cache()
    raw: Union[bytes, bytearray, None] = local_cache.get(f"journeys:{journey_uid}:meta")
    if raw is None:
        return None

    return CachedJourneyMeta.parse_raw(raw, content_type="application/json")


async def set_cached_journey_meta(
    itgs: Itgs, journey_uid: str, meta: CachedJourneyMeta
) -> None:
    """Stores the cached journey meta information"""
    local_cache = await itgs.local_cache()
    local_cache.set(
        f"journeys:{journey_uid}:meta", meta.json().encode("utf-8"), expire=60 * 60 * 24
    )


async def get_journey_meta_from_database(
    itgs: Itgs, journey_uid: str
) -> Optional[CachedJourneyMeta]:
    """Gets the journey meta information from the database, if a journey with
    the given uid exists, otherwise returns None
    """
    conn = await itgs.conn()
    cursor = conn.cursor("none")

    response = await cursor.execute(
        """
        SELECT
            journeys.prompt,
            content_files.duration_seconds
        FROM journeys
        JOIN content_files ON journeys.audio_content_file_id = content_files.id
        WHERE
            journeys.uid = ?
        """,
        (journey_uid,),
    )
    if not response.results:
        return None

    prompt: Dict[str, Any] = json.loads(response.results[0][0])
    duration_seconds: float = response.results[0][1]
    bins: int
    if duration_seconds <= 1:
        bins = 1
    else:
        bins = 2 ** math.ceil(math.log2(duration_seconds)) - 1

    return CachedJourneyMeta(
        uid=journey_uid, duration_seconds=duration_seconds, bins=bins, prompt=prompt
    )


async def get_journey_meta(itgs: Itgs, journey_uid: str) -> Optional[CachedJourneyMeta]:
    """Loads the given journey's meta information from the cache, if it's
    already cached, otherwise from the database and storing it in the cache

    Returns None only if the journey is not available from the database
    """
    meta = await get_cached_journey_meta(itgs, journey_uid)
    if meta is not None:
        return meta

    meta = await get_journey_meta_from_database(itgs, journey_uid)
    if meta is not None:
        await set_cached_journey_meta(itgs, journey_uid, meta)

    return meta


class JourneyMetaPurgePubSubMessage(BaseModel):
    journey_uid: str = Field(
        description="The UID of the journey to purge the meta information for"
    )
    min_checked_at: float = Field(
        description=(
            "When this purge was triggered; it's not necessary to purge information "
            "that was cached after this time"
        )
    )


async def purge_journey_meta(itgs: Itgs, journey_uid: str) -> None:
    """Purges any cached journey meta information on the journey with the given uid from
    all instances, forcing it to be reloaded from the database. This should be called
    if the journey meta information has been updated in the database

    Args:
        itgs (Itgs): The integrations to (re)use
        journey_uid (str): The journey uid to purge
    """
    redis = await itgs.redis()
    await redis.publish(
        "ps:journeys:meta:purge".encode("ascii"),
        JourneyMetaPurgePubSubMessage(
            journey_uid=journey_uid,
            min_checked_at=time.time(),
        )
        .json()
        .encode("utf-8"),
    )


async def purge_journey_meta_loop() -> NoReturn:
    """This loop will listen for purge requests from ps:journeys:meta:purge and
    will purge the journey meta information from our local cache, ensuring it
    gets reloaded from the nearest non-local cache or source. It runs continuously
    in the background and is invoked by the admin journey update endpoint(s) via
    the purge_journey_meta function
    """
    try:
        async with pps.PPSSubscription(
            pps.instance, "ps:journeys:meta:purge", hint="journey_meta"
        ) as sub:
            async for raw_data in sub:
                message = JourneyMetaPurgePubSubMessage.parse_raw(
                    raw_data, content_type="application/json"
                )
                async with Itgs() as itgs:
                    local_cache = await itgs.local_cache()
                    local_cache.delete(f"journeys:{message.journey_uid}:meta")
    finally:
        print("purge journey meta loop exiting")
