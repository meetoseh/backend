from dataclasses import dataclass
import math
import re
import secrets
import time
from typing import Any, Callable, Dict, Generic, Iterable, List, Literal, Optional, Tuple, TypeVar

from fastapi.responses import Response
from pydantic import BaseModel, Field
from image_files.models import ImageFileRef
from image_files.auth import create_jwt as create_image_file_jwt
from interactive_prompts.events.models import (
    ERROR_INTERACTIVE_PROMPT_IMPOSSIBLE_PROMPT_TIME_RESPONSE,
    ERROR_INTERACTIVE_PROMPT_NOT_FOUND_RESPONSE,
    ERROR_INTERACTIVE_PROMPT_SESSION_ALREADY_ENDED_RESPONSE,
    ERROR_INTERACTIVE_PROMPT_SESSION_ALREADY_STARTED_RESPONSE,
    ERROR_INTERACTIVE_PROMPT_SESSION_HAS_LATER_EVENT_RESPONSE,
    ERROR_INTERACTIVE_PROMPT_SESSION_HAS_SAME_EVENT_AT_SAME_TIME_RESPONSE,
    ERROR_INTERACTIVE_PROMPT_SESSION_NOT_FOUND_RESPONSE,
    ERROR_INTERACTIVE_PROMPT_SESSION_NOT_STARTED_RESPONSE,
    CreateInteractivePromptEventResponse,
)
from interactive_prompts.lib.read_interactive_prompt_meta import (
    read_interactive_prompt_meta,
)
from interactive_prompts.models.prompt import Prompt
from functools import lru_cache
from models import ERROR_401_TYPE, ERROR_403_TYPE, StandardErrorResponse
from itgs import Itgs
from models import StandardErrorResponse
from pypika import Query, Table, Parameter, Order, Tuple as SqlAliasable
from pypika.terms import Term, ExistsCriterion, ContainsCriterion
from pypika.queries import QueryBuilder
import auth
import interactive_prompts.auth


@dataclass
class InteractivePromptAugmentedMeta:
    """Carries over the information from read_interactive_prompt_meta, but adds
    some additional information that is useful for events-related endpoints. This
    information doesn't require any database queries.
    """

    uid: str
    """The uid of the interactive prompt"""
    prompt: Prompt
    """Information about the prompt"""
    duration_seconds: int
    """The duration of the interactive prompt in seconds"""
    journey_subcategory: Optional[str]
    """If this interactive prompt is for a journey, the internal name of the
    journey subcategory. Otherwise, None.
    """
    bins: int
    """How many bins are used in the fenwick tree"""


@lru_cache(maxsize=128)
def compute_bins(duration_seconds: int) -> int:
    if duration_seconds <= 1:
        return 1
    else:
        return 2 ** math.ceil(math.log2(duration_seconds)) - 1


async def get_interactive_prompt_meta(
    itgs: Itgs, uid: str
) -> Optional[InteractivePromptAugmentedMeta]:
    """Reads the interactive prompt meta for the interactive prompt with the given
    uid. This will fetch from the nearest available source, filling intermediary
    caches as it goes.

    Args:
        itgs (Itgs): The integrations to use to connect to networked services
        uid (str): The uid of the interactive prompt

    Returns:
        InteractivePromptAugmentedMeta, None: The interactive prompt meta, or None
            if there is no interactive prompt with that uid
    """
    meta = await read_interactive_prompt_meta(itgs, interactive_prompt_uid=uid)
    if meta is None:
        return None
    return InteractivePromptAugmentedMeta(
        uid=uid,
        prompt=meta.prompt,
        duration_seconds=meta.duration_seconds,
        journey_subcategory=meta.journey_subcategory,
        bins=compute_bins(meta.duration_seconds),
    )


@dataclass
class SuccessfulAuthResult:
    user_sub: str
    """The sub of the user that was authenticated."""

    interactive_prompt_uid: str
    """The UID of the interactive prompt which they have access too"""

    user_claims: Optional[Dict[str, Any]]
    """The claims of the user token, typically for debugging, if applicable for the token type"""

    interactive_prompt_claims: Optional[Dict[str, Any]]
    """The claims of the interactive prompt token, typically for debugging, if applicable for the token type"""


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


async def auth_create_interactive_prompt_event(
    itgs: Itgs,
    *,
    authorization: Optional[str],
    interactive_prompt_jwt: str,
    interactive_prompt_uid: str,
) -> AuthResult:
    """Performs the standard authorization for a create interactive prompt event,
    which involves both an authorization header (which user is performing the
    action) and an interactive prompt jwt (proof they are allowed to view/interact with the
    interactive prompt).

    Args:
        authorization (str, None): The value provided for the authorization header,
            or None if it was not provided.
        interactive_prompt_jwt (str): The interactive prompt jwt provided in the request.
            Should not be prefixed with `bearer `
        interactive_prompt_uid (str): The interactive prompt uid that the user specified.
            This is not really necessary for the backend, since it's in the jwt, but it ensures
            the client doesn't have a token mixup style bug.
    """
    if interactive_prompt_jwt.startswith("bearer "):
        return AuthResult(
            result=None,
            error_type="bad_format",
            error_response=Response(
                content=StandardErrorResponse[ERROR_401_TYPE](
                    type="bad_format",
                    message=(
                        "The interactive prompt JWT should not be prefixed with `bearer ` when not sent "
                        "as a header parameter."
                    ),
                ).model_dump_json(),
                headers={
                    "Content-Type": "application/json; charset=utf-8"
                },
                status_code=401,
            ),
        )

    interactive_prompt_auth_result = await interactive_prompts.auth.auth_any(
        itgs, f"bearer {interactive_prompt_jwt}"
    )
    if interactive_prompt_auth_result.result is None:
        return AuthResult(
            result=None,
            error_type=interactive_prompt_auth_result.error_type,
            error_response=interactive_prompt_auth_result.error_response,
        )

    if (
        interactive_prompt_auth_result.result.interactive_prompt_uid
        != interactive_prompt_uid
    ):
        return AuthResult(
            result=None,
            error_type="invalid",
            error_response=Response(
                content=StandardErrorResponse[ERROR_403_TYPE](
                    type="invalid",
                    message=(
                        "You are not authorized to perform this action on this interactive prompt. "
                        "The provided JWT is valid, but not for the indicated prompt uid. "
                        "This is a token mix-up bug; to help debug, recall that the claims of the "
                        "JWT are not encrypted, and specifically the sub of the JWT should match "
                        "the interactive prompt uid. You can manually decode the JWT at jwt.io."
                    ),
                ).model_dump_json(),
                headers={
                    "Content-Type": "application/json; charset=utf-8"
                },
                status_code=403,
            ),
        )

    user_auth_result = await auth.auth_any(itgs, authorization)
    if user_auth_result.result is None:
        return AuthResult(
            result=None,
            error_type=user_auth_result.error_type,
            error_response=user_auth_result.error_response,
        )

    return AuthResult(
        result=SuccessfulAuthResult(
            user_sub=user_auth_result.result.sub,
            interactive_prompt_uid=interactive_prompt_auth_result.result.interactive_prompt_uid,
            user_claims=user_auth_result.result.claims,
            interactive_prompt_claims=interactive_prompt_auth_result.result.claims,
        ),
        error_type=None,
        error_response=None,
    )


EventTypeT = TypeVar("EventTypeT", bound=str)
EventDataT = TypeVar("EventDataT", bound=BaseModel)


@dataclass
class CreateInteractivePromptEventSuccessResult(Generic[EventTypeT, EventDataT]):
    """The information available when successfully creating a new interactive prompt event"""

    content: CreateInteractivePromptEventResponse[EventTypeT, EventDataT]
    """The response content to return to the client"""

    created_at: float
    """The unix timestamp assigned to when the event was created."""

    @property
    def response(self) -> Response:
        """The response content wrapped in an actual response"""
        return Response(
            content=self.content.model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=201,
        )


@dataclass
class CreateInteractivePromptEventResult(Generic[EventTypeT, EventDataT]):
    """The result of attempting to create a new interactive prompt event."""

    result: Optional[CreateInteractivePromptEventSuccessResult]
    """If the event was successfully created, the result"""

    error_type: Optional[
        Literal[
            "not_found",
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
    ]
    """The reasons we might reject a request to create a new interactive prompt event,
    which aren't related to the event data. The event data should be validated
    prior to calling create_interactive_prompt_event.
    """

    error_response: Optional[Response]
    """If the event was not successfully created, the response to return to the client"""

    @property
    def success(self) -> bool:
        """Convenience function to determine if the result was successful"""
        return self.result is not None


class InteractivePromptEventPubSubMessage(
    BaseModel, Generic[EventTypeT, EventDataT]
):
    """Describes a message that is published to the pubsub topic for an interactive prompt"""

    uid: str = Field(description="the uid of the new event")
    user_sub: str = Field(description="the sub of the user who created the event")
    session_uid: str = Field(
        description="the uid of the session the event was created in"
    )
    evtype: EventTypeT = Field(description="the type of the event")
    data: EventDataT = Field(description="the data of the event")
    icon: Optional[str] = Field(
        description="if there is an icon associated with this event, the uid of the corresponding image file"
    )
    prompt_time: float = Field(description="the prompt time of the event")
    created_at: float = Field(
        description="the unix timestamp of when the event was created"
    )


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

    - increment the new rating at the prompt time
    - decrement the old rating at the prompt time

    focusing on the second part, that becomes

    ```txt
    decrement from each rating at the prompt time
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
    INSERT INTO interactive_prompt_event_fenwick_trees (
        interactive_prompt_id, category, category_value, idx, val
    )
    SELECT
        interactive_prompts.id,
        ?,  /* category */
        ?,  /* category value; m values to consider */
        ?,  /* idx to update; at most log(n) values will need updating */
        ?   /* the amount to initialize at, only used if the row doesn't exist */
    FROM interactive_prompts
    WHERE
        interactive_prompts.uid = ? /* uid of the interactive prompt */
        /* verifies our event was actually inserted to avoid duplicating sanity checks */
        AND EXISTS (
            SELECT 1 FROM interactive_prompt_events
            WHERE interactive_prompt_events.uid = ? /* the event uid we're trying to insert */
        )
        AND (
            /* this would be the condition */
            1=1
        )
    ON CONFLICT (interactive_prompt_id, category, category_value, idx)
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
    enumerated in the interactive_prompt_event_fenwick_trees database docs
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
    """Only relevant if simple is False. This is the field in the interactive_prompt_events
    data which contains the category value. For example, if the category is
    `numeric_active`, this would be `rating`, since for `numeric_prompt_response`
    the interactive prompt event data contains a `rating` field.

    If simple is True, this value is ignored.
    """

    def to_queries(
        self,
        *,
        interactive_prompt_event_uid: str,
        prompt_time: int,
        interactive_prompt_meta: InteractivePromptAugmentedMeta,
    ) -> List[Tuple[str, List[Any]]]:
        """Produces the required sql queries to update the fenwick tree described
        by this prefix sum update.

        Args:
            interactive_prompt_event_uid (str): The UID of the interactive
                prompt event being inserted. The fenwick tree is only updated
                if this event is actually inserted.
            prompt_time (float): The prompt time of the event being inserted.
            interactive_prompt_meta (InteractivePromptAugmentedMeta): Cached meta
                information about the interactive prompt, required to determine
                what queries are required. This only contains immutable
                information about the interactive prompt and does not effect the
                atomicity of the queries.

        Returns:
            The queries to execute, in the form of (query, params) tuples.
        """
        bin_width = (
            interactive_prompt_meta.duration_seconds / interactive_prompt_meta.bins
        )
        bin_idx = min(
            max(0, int(prompt_time / bin_width)), interactive_prompt_meta.bins - 1
        )

        indices = []
        one_based_idx = bin_idx + 1
        while one_based_idx <= interactive_prompt_meta.bins:
            indices.append(one_based_idx - 1)
            one_based_idx += one_based_idx & -one_based_idx

        qmark_list = ", ".join(["(?)"] * len(indices))

        if self.simple:
            conflict_key = (
                "(interactive_prompt_id, category, category_value, idx)"
                if self.category_value is not None
                else "(interactive_prompt_id, category, idx) WHERE category_value IS NULL"
            )
            return [
                (
                    re.sub(
                        r"\s+",
                        " ",
                        f"""
                        WITH indices(idx) AS (VALUES {qmark_list})
                        INSERT INTO interactive_prompt_event_fenwick_trees (
                            interactive_prompt_id, category, category_value, idx, val
                        )
                        SELECT
                            interactive_prompts.id, ?, ?, indices.idx, ?
                        FROM interactive_prompts, indices
                        WHERE
                            interactive_prompts.uid = ?
                            AND EXISTS (SELECT 1 FROM interactive_prompt_events WHERE interactive_prompt_events.uid=?)
                        ON CONFLICT {conflict_key}
                        DO UPDATE SET val = val + ?
                        """,
                    ).strip(),
                    [
                        *indices,
                        self.category,
                        self.category_value,
                        self.amount,
                        interactive_prompt_meta.uid,
                        interactive_prompt_event_uid,
                        self.amount,
                    ],
                )
            ]

        return [
            (
                re.sub(
                    r"\s+",
                    " ",
                    f"""
                    WITH indices(idx) AS (VALUES {qmark_list})
                    INSERT INTO interactive_prompt_event_fenwick_trees (
                        interactive_prompt_id, category, category_value, idx, val
                    )
                    SELECT
                        interactive_prompts.id, ?, json_extract(interactive_prompt_events.data, ?), indices.idx, ?
                    FROM interactive_prompts, indices, interactive_prompt_events
                    WHERE
                        interactive_prompts.uid = ?
                        AND interactive_prompt_events.uid != ?
                        AND EXISTS (
                            SELECT 1 FROM interactive_prompt_events AS ipe
                            WHERE ipe.interactive_prompt_session_id = interactive_prompt_events.interactive_prompt_session_id
                              AND ipe.uid = ?
                        )
                        AND interactive_prompt_events.evtype = ?
                        AND NOT EXISTS (
                            SELECT 1 FROM interactive_prompt_events AS ipe
                            WHERE ipe.interactive_prompt_session_id = interactive_prompt_events.interactive_prompt_session_id
                              AND ipe.evtype = ?
                              AND ipe.prompt_time > interactive_prompt_events.prompt_time
                              AND ipe.uid != ?
                        )
                    ON CONFLICT (interactive_prompt_id, category, category_value, idx)
                    DO UPDATE SET val = val + ?
                    ON CONFLICT (interactive_prompt_id, category, idx) WHERE category_value IS NULL
                    DO UPDATE SET val = val + ?
                    """,
                ).strip(),
                [
                    *indices,
                    self.category,
                    f"$.{self.event_data_field}",
                    self.amount,
                    interactive_prompt_meta.uid,
                    interactive_prompt_event_uid,
                    interactive_prompt_event_uid,
                    self.event_type,
                    self.event_type,
                    interactive_prompt_event_uid,
                    self.amount,
                    self.amount,
                ],
            )
        ]


async def create_interactive_prompt_event(
    itgs: Itgs,
    *,
    interactive_prompt_uid: str,
    user_sub: str,
    session_uid: str,
    event_type: EventTypeT,
    event_data: EventDataT,
    prompt_time: float,
    bonus_terms: Optional[List[Tuple[Term, List[Any]]]] = None,
    bonus_error_checks: Optional[
        List[Tuple[Term, List[Any], Callable[[], CreateInteractivePromptEventResult]]]
    ] = None,
    prefix_sum_updates: Optional[List[PrefixSumUpdate]] = None,
    store_event_data: Optional[BaseModel] = None,
) -> CreateInteractivePromptEventResult[EventTypeT, EventDataT]:
    """Creates a new interactive prompt event for the given interactive prompt by
    the given user with the given type, data and prompt time. This will assign a
    uid and created_at time to the event, and ensure it's persisted and
    propagated to listeners.

    Args:
        itgs (Itgs): The integrations for networked services
        interactive_prompt_uid (str): The uid of the interactive prompt to create the event for
        user_sub (str): The sub of the user creating the event
        session_uid (str): The session uid of the user creating the event
        event_type (EventTypeT): The type of the event
        event_data (EventDataT): The data of the event
        prompt_time (float): The prompt time of the event
        bonus_terms (list[tuple[Term, list[Any]]], None): If specified, these terms
            will be added to the where part of the INSERT statement. These terms will
            be able to reference `interactive_prompt_sessions` which can be assumed to be
            for the correct interactive prompt session (with the user and interactive
            prompt already verified).

            Example:

    ```py
    interactive_prompt_sessions = Table('interactive_prompt_sessions')
    other_stuffs = Table('other_stuffs')
    bonus_terms = [
        (
            ExistsCriterion(
                Query.from_(other_stuffs)
                .select(1)
                .where(other_stuffs.interactive_prompt_session_id == interactive_prompt_sessions.id)
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
        WHERE "other_stuffs"."interactive_prompt_session_id" = "interactive_prompt_sessions"."id"
            AND "other_stuffs"."uid" = ?
    )
    ```

            and this will send the query parameter `some-uid` in the appropriate spot.
        bonus_error_checks (list[tuple[Term, list[Any], () -> CreateInteractivePromptEventResult]], None):
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
            checks can assume that, for example, the interactive prompt session
            exists and is for the correct user/interactive prompt.

            These terms will NOT be able to reference
            `interactive_prompt_sessions`, though they can get that reference
            trivially with an exists criterion.

            Example:

    ```py
    interactive_prompt_sessions = Table('interactive_prompt_sessions')
    other_stuffs = Table('other_stuffs')
    bonus_error_checks = [
        (
            ExistsCriterion(
                Query.from_(other_stuffs)
                .select(1)
                .where(
                    ExistsCriterion(
                        Query.from_(interactive_prompt_sessions)
                        .where(interactive_prompt_sessions.id == other_stuffs.interactive_prompt_session_id)
                        .where(interactive_prompt_sessions.uid == Parameter('?'))
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
                    SELECT 1 FROM "interactive_prompt_sessions"
                    WHERE "interactive_prompt_sessions"."id" = "other_stuffs"."interactive_prompt_session_id"
                        AND "interactive_prompt_sessions"."uid" = ?
                )
                AND "other_stuffs"."uid" = ?
        )
    ) "b7"
    ```

            Note how the column alias is generated to a short unique value to reduce
            network traffic.

        prefix_sum_updates (list[PrefixSumUpdate], None): If specified, these
            prefix sum updates will be performed iff the interactive prompt event is
            stored. This is required for keeping the stats endpoint up to date.
            See PrefixSumUpdate for more details.

        store_event_data (BaseModel, None): If specified, instead of storing the event data
            in the database, we will instead store the json representation of this in the
            database. Useful if there is redundant data in the event which is helpful for
            clients but not for us.

    Returns:
        CreateINteractivePromptEventResult: The result of the operation
    """
    if prompt_time < 0:
        return CreateInteractivePromptEventResult(
            result=None,
            error_type="impossible_prompt_time",
            error_response=ERROR_INTERACTIVE_PROMPT_IMPOSSIBLE_PROMPT_TIME_RESPONSE,
        )

    event_uid = f"oseh_ipe_{secrets.token_urlsafe(16)}"
    serd_event_data = (
        event_data.model_dump_json() if store_event_data is None else store_event_data.model_dump_json()
    )
    created_at = time.time()

    interactive_prompt_events = Table("interactive_prompt_events")
    interactive_prompt_sessions = Table("interactive_prompt_sessions")
    users = Table("users")
    interactive_prompts = Table("interactive_prompts")
    content_files = Table("content_files")
    interactive_prompt_events_inner = interactive_prompt_events.as_("ipe")

    query: QueryBuilder = (
        Query.into(interactive_prompt_events)
        .columns(
            interactive_prompt_events.uid,
            interactive_prompt_events.interactive_prompt_session_id,
            interactive_prompt_events.evtype,
            interactive_prompt_events.data,
            interactive_prompt_events.prompt_time,
            interactive_prompt_events.created_at,
        )
        .select(
            Parameter("?"),
            interactive_prompt_sessions.id,
            Parameter("?"),
            Parameter("?"),
            Parameter("?"),
            Parameter("?"),
        )
        .from_(interactive_prompt_sessions)
        .where(interactive_prompt_sessions.uid == Parameter("?"))
    )
    qargs = [
        event_uid,
        event_type,
        serd_event_data,
        prompt_time,
        created_at,
        session_uid,
    ]

    session_is_for_user: Term = ExistsCriterion(
        Query.from_(users)
        .select(1)
        .where(users.id == interactive_prompt_sessions.user_id)
        .where(users.sub == Parameter("?"))
    )
    session_is_for_user_qargs = [user_sub]

    query = query.where(session_is_for_user)
    qargs.extend(session_is_for_user_qargs)

    session_is_for_interactive_prompt: Term = ExistsCriterion(
        Query.from_(interactive_prompts)
        .select(1)
        .where(
            interactive_prompts.id == interactive_prompt_sessions.interactive_prompt_id
        )
        .where(interactive_prompts.uid == Parameter("?"))
    )
    session_is_for_interactive_prompt_qargs = [interactive_prompt_uid]

    query = query.where(session_is_for_interactive_prompt)
    qargs.extend(session_is_for_interactive_prompt_qargs)

    prompt_time_is_at_or_before_end: Term = ExistsCriterion(
        Query.from_(interactive_prompts)
        .select(1)
        .where(
            interactive_prompts.id == interactive_prompt_sessions.interactive_prompt_id
        )
        .where(interactive_prompts.duration_seconds >= Parameter("?"))
    )
    prompt_time_is_at_or_before_end_qargs = [prompt_time]

    query = query.where(prompt_time_is_at_or_before_end)
    qargs.extend(prompt_time_is_at_or_before_end_qargs)

    session_has_event_term: Term = ExistsCriterion(
        Query.from_(interactive_prompt_events_inner)
        .select(1)
        .where(
            interactive_prompt_events_inner.interactive_prompt_session_id
            == interactive_prompt_sessions.id
        )
    )
    session_has_event_qargs = []

    if event_type == "join":
        query = query.where(~session_has_event_term)
    else:
        query = query.where(session_has_event_term)

    qargs.extend(session_has_event_qargs)

    session_is_finished_term: ContainsCriterion = Parameter("?").isin(
        Query.from_(interactive_prompt_events_inner)
        .select(interactive_prompt_events_inner.evtype)
        .where(
            interactive_prompt_events_inner.interactive_prompt_session_id
            == interactive_prompt_sessions.id
        )
        .orderby(interactive_prompt_events_inner.prompt_time, order=Order.desc)
        .limit(1)
    )
    session_is_finished_qargs = ["leave"]

    query = query.where(session_is_finished_term.negate())
    qargs.extend(session_is_finished_qargs)

    session_has_later_event_term: Term = ExistsCriterion(
        Query.from_(interactive_prompt_events_inner)
        .select(1)
        .where(
            interactive_prompt_events_inner.interactive_prompt_session_id
            == interactive_prompt_sessions.id
        )
        .where(interactive_prompt_events_inner.prompt_time > Parameter("?"))
    )
    session_has_later_event_qargs = [prompt_time]

    query = query.where(~session_has_later_event_term)
    qargs.extend(session_has_later_event_qargs)

    session_has_same_event_type_at_same_time_term: Term = ExistsCriterion(
        Query.from_(interactive_prompt_events_inner)
        .select(1)
        .where(
            interactive_prompt_events_inner.interactive_prompt_session_id
            == interactive_prompt_sessions.id
        )
        .where(interactive_prompt_events_inner.prompt_time == Parameter("?"))
        .where(interactive_prompt_events_inner.evtype == Parameter("?"))
    )
    session_has_same_event_type_at_same_time_qargs = [prompt_time, event_type]

    query = query.where(~session_has_same_event_type_at_same_time_term)
    qargs.extend(session_has_same_event_type_at_same_time_qargs)

    if bonus_terms:
        for term, term_qargs in bonus_terms:
            query = query.where(term)
            qargs.extend(term_qargs)

    queries: List[Tuple[str, Iterable[Any]]] = [(query.get_sql(), qargs)]

    queries.append(
        (
            "INSERT INTO interactive_prompt_event_counts "
            "(interactive_prompt_id, bucket, total) "
            "SELECT interactive_prompts.id, ?, 1 "
            "FROM interactive_prompts "
            "WHERE"
            " interactive_prompts.uid = ?"
            " AND EXISTS (SELECT 1 FROM interactive_prompt_events WHERE interactive_prompt_events.uid = ?) "
            "ON CONFLICT (interactive_prompt_id, bucket) DO UPDATE SET total = interactive_prompt_event_counts.total + 1",
            (int(prompt_time), interactive_prompt_uid, event_uid),
        )
    )

    interactive_prompt_meta = await get_interactive_prompt_meta(
        itgs, interactive_prompt_uid
    )
    if interactive_prompt_meta is None:
        return CreateInteractivePromptEventResult(
            result=None,
            error_type="not_found",
            error_response=ERROR_INTERACTIVE_PROMPT_NOT_FOUND_RESPONSE,
        )
    
    if prompt_time > interactive_prompt_meta.duration_seconds:
        return CreateInteractivePromptEventResult(
            result=None,
            error_type="impossible_prompt_time",
            error_response=ERROR_INTERACTIVE_PROMPT_IMPOSSIBLE_PROMPT_TIME_RESPONSE,
        )

    if interactive_prompt_meta is None:
        return CreateInteractivePromptEventResult(
            result=None,
            error_type="not_found",
            error_response=ERROR_INTERACTIVE_PROMPT_NOT_FOUND_RESPONSE,
        )

    for update in prefix_sum_updates or []:
        queries.extend(
            update.to_queries(
                interactive_prompt_event_uid=event_uid,
                prompt_time=int(prompt_time),
                interactive_prompt_meta=interactive_prompt_meta,
            )
        )

    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    response = (await cursor.executemany3(queries))[0]
    if response.rows_affected is None or response.rows_affected < 1:

        def wrap_with_interactive_prompt_sessions(
            term: Optional[Term], term_args: List[Any], *, is_strict: bool = True
        ) -> Tuple[Term, List[Any]]:
            result: QueryBuilder = (
                Query.from_(interactive_prompt_sessions)
                .select(1)
                .where(interactive_prompt_sessions.uid == Parameter("?"))
            )
            result_args = [session_uid]

            if is_strict:
                # whenever is_strict is false, it should behave the same as when
                # is_strict is true. we set is_strict to False when we've already
                # verified these parts, for simplicity of the query & for performance
                result = result.where(session_is_for_user)
                result_args.extend(session_is_for_user_qargs)

                result = result.where(session_is_for_interactive_prompt)
                result_args.extend(session_is_for_interactive_prompt_qargs)

            if term is not None:
                result = result.where(term)
                result_args.extend(term_args)

            return ExistsCriterion(result), result_args

        terms_and_args: List[
            Tuple[Term, List[Any], Callable[[], CreateInteractivePromptEventResult]]
        ] = [
            (
                ExistsCriterion(
                    Query.from_(interactive_prompts)
                    .select(1)
                    .where(interactive_prompts.uid == Parameter("?"))
                ),
                [interactive_prompt_uid],
                lambda: CreateInteractivePromptEventResult(
                    result=None,
                    error_type="not_found",
                    error_response=ERROR_INTERACTIVE_PROMPT_NOT_FOUND_RESPONSE,
                ),
            ),
            (
                *wrap_with_interactive_prompt_sessions(None, []),
                lambda: CreateInteractivePromptEventResult(
                    result=None,
                    error_type="session_not_found",
                    error_response=ERROR_INTERACTIVE_PROMPT_SESSION_NOT_FOUND_RESPONSE,
                ),
            ),
            (
                (
                    *wrap_with_interactive_prompt_sessions(
                        session_has_event_term, session_has_event_qargs, is_strict=False
                    ),
                    lambda: CreateInteractivePromptEventResult(
                        result=None,
                        error_type="session_not_started",
                        error_response=ERROR_INTERACTIVE_PROMPT_SESSION_NOT_STARTED_RESPONSE,
                    ),
                )
                if event_type != "join"
                else (
                    *wrap_with_interactive_prompt_sessions(
                        ~session_has_event_term,
                        session_has_event_qargs,
                        is_strict=False,
                    ),
                    lambda: CreateInteractivePromptEventResult(
                        result=None,
                        error_type="session_already_started",
                        error_response=ERROR_INTERACTIVE_PROMPT_SESSION_ALREADY_STARTED_RESPONSE,
                    ),
                )
            ),
            (
                *wrap_with_interactive_prompt_sessions(
                    ~session_is_finished_term,
                    session_is_finished_qargs,
                    is_strict=False,
                ),
                lambda: CreateInteractivePromptEventResult(
                    result=None,
                    error_type="session_already_ended",
                    error_response=ERROR_INTERACTIVE_PROMPT_SESSION_ALREADY_ENDED_RESPONSE,
                ),
            ),
            (
                *wrap_with_interactive_prompt_sessions(
                    ~session_has_later_event_term,
                    session_has_later_event_qargs,
                    is_strict=False,
                ),
                lambda: CreateInteractivePromptEventResult(
                    result=None,
                    error_type="session_has_later_event",
                    error_response=ERROR_INTERACTIVE_PROMPT_SESSION_HAS_LATER_EVENT_RESPONSE,
                ),
            ),
            (
                *wrap_with_interactive_prompt_sessions(
                    ~session_has_same_event_type_at_same_time_term,
                    session_has_same_event_type_at_same_time_qargs,
                    is_strict=False,
                ),
                lambda: CreateInteractivePromptEventResult(
                    result=None,
                    error_type="session_has_same_event_at_same_time",
                    error_response=ERROR_INTERACTIVE_PROMPT_SESSION_HAS_SAME_EVENT_AT_SAME_TIME_RESPONSE,
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
        assert response.results is not None
        for success, (_, _, error_fn) in zip(response.results[0], terms_and_args):
            if not success:
                return error_fn()

        return CreateInteractivePromptEventResult(
            result=None,
            error_type="impossible_prompt_time",
            error_response=ERROR_INTERACTIVE_PROMPT_IMPOSSIBLE_PROMPT_TIME_RESPONSE,
        )

    icon: Optional[ImageFileRef] = None
    cursor = conn.cursor("none")
    response = await cursor.execute(
        """
        SELECT
            image_files.uid
        FROM image_files, users, user_profile_pictures
        WHERE
            image_files.id = user_profile_pictures.image_file_id
            AND user_profile_pictures.user_id = users.id 
            AND user_profile_pictures.latest = 1
            AND users.sub = ?
        """,
        (user_sub,),
    )
    if response.results and response.results[0] is not None:
        icon = ImageFileRef(
            uid=response.results[0][0],
            jwt=await create_image_file_jwt(itgs, response.results[0][0]),
        )

    result = CreateInteractivePromptEventResult(
        result=CreateInteractivePromptEventSuccessResult(
            content=CreateInteractivePromptEventResponse(
                uid=event_uid,
                user_sub=user_sub,
                session_uid=session_uid,
                type=event_type,
                prompt_time=prompt_time,
                icon=icon,
                data=event_data,
            ),
            created_at=created_at,
        ),
        error_type=None,
        error_response=None,
    )

    message = InteractivePromptEventPubSubMessage(
        uid=event_uid,
        user_sub=user_sub,
        session_uid=session_uid,
        evtype=event_type,
        data=event_data,
        icon=icon.uid if icon is not None else None,
        prompt_time=prompt_time,
        created_at=created_at,
    )

    redis = await itgs.redis()
    await redis.publish(
        f"ps:interactive_prompts:{interactive_prompt_uid}:events".encode("utf-8"),
        message.model_dump_json().encode("utf-8"),
    )

    return result


async def get_display_name(itgs: Itgs, result: SuccessfulAuthResult) -> str:
    """Gets the preferred display name for the user authorized with the given
    result
    """
    user_claims = result.user_claims
    if user_claims is not None:
        if "given_name" in user_claims:
            return user_claims["given_name"]
        elif "name" in user_claims:
            name: str = user_claims["name"]
            return name.split(" ")[0]
        elif "preferred_username" in user_claims:
            return user_claims["preferred_username"]
        elif "nickname" in user_claims:
            return user_claims["nickname"]
    return "Anonymous"
