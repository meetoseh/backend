"""Performs basic analysis of the client flow graph, caching in redis. Relies
on active cache busting.
"""

import asyncio
from collections import deque
import secrets
import time
from typing import (
    AsyncIterator,
    Dict,
    FrozenSet,
    Iterator,
    List,
    Literal,
    Optional,
    Set,
    Tuple,
    Union,
    cast,
)
from pydantic import BaseModel, Field, TypeAdapter
from dataclasses import dataclass

import pytz
from lib.client_flows.client_flow_predicate import (
    CheckFlowPredicateContext,
    ClientFlowPredicateParams,
    Wrapped,
    check_flow_predicate,
)
from lib.client_flows.flow_cache import get_client_flow, get_valid_client_flow_slugs
import lib.client_flows.helper as helper
from lib.client_flows.client_flow_rule import ClientFlowRules
from error_middleware import handle_error, handle_warning
from itgs import Itgs
import hashlib
import io
import base64

from lib.client_flows.client_flow_screen import ClientFlowScreen, ClientFlowScreenFlag
from lib.client_flows.screen_cache import get_client_screen
from lib.client_flows.screen_flags import ClientScreenFlag
from lifespan import lifespan_handler
import perpetual_pub_sub as pps
from redis_helpers.client_flow_graph_analysis_acquire_read_lock import (
    safe_client_flow_graph_analysis_acquire_read_lock,
)
from redis_helpers.client_flow_graph_analysis_acquire_write_lock import (
    safe_client_flow_graph_analysis_acquire_write_lock,
)
from redis_helpers.client_flow_graph_analysis_read_paths_page import (
    safe_client_flow_graph_analysis_read_paths_page,
)
from redis_helpers.client_flow_graph_analysis_read_reachable import (
    safe_client_flow_graph_analysis_read_reachable,
)
from redis_helpers.client_flow_graph_analysis_release_read_lock import (
    safe_client_flow_graph_analysis_release_read_lock,
)
from redis_helpers.client_flow_graph_analysis_release_write_lock import (
    safe_client_flow_graph_analysis_release_write_lock,
)
from redis_helpers.client_flow_graph_analysis_write_batch import (
    ClientFlowGraphAnalysisWriteBatchResult,
    safe_client_flow_graph_analysis_write_batch,
)
from visitors.lib.get_or_create_visitor import VisitorSource


IGNORE_FORWARD_TARGETS: FrozenSet[bytes] = frozenset((b"skip", b"empty"))


class ClientFlowAnalysisEnvironment(BaseModel):
    """Describes the state of the user for the purposes of matching predicates
    while analyzing a client flow
    """

    version: Optional[int] = Field(
        description="Which screen version the client is using. None is for a client before they "
        "sent screen versions, i.e., the minimum version."
    )
    account_created_at: int = Field(
        description="When the user created their account in seconds since the epoch"
    )
    now: int = Field(
        description="The current time in seconds since the epoch (for within analysis)"
    )
    last_journey_rating: Optional[int] = Field(
        description="The rating the user gave to their last journey (1-loved, 2-liked, 3-disliked, 4-hated), "
        "or None if they either have not taken a journey or did not rate the last journey they took"
    )
    journeys_today: int = Field(description="How many journeys they took today")
    journal_entries_in_history_today: int = Field(
        description="How many journal entries they made today"
    )
    has_oseh_plus: bool = Field(description="If they have oseh+")
    platform: VisitorSource = Field(description="The platform they are on")

    def to_redis_identifier(self) -> bytes:
        """Converts these settings to a stable string identifier that can be used"""
        raw = io.BytesIO()
        raw.write(b'{"version": ')
        raw.write(str(self.version).encode("ascii"))
        raw.write(b', "account_created_at": ')
        raw.write(str(self.account_created_at).encode("ascii"))
        raw.write(b', "now": ')
        raw.write(str(self.now).encode("ascii"))
        raw.write(b', "last_journey_rating": ')
        raw.write(str(self.last_journey_rating).encode("ascii"))
        raw.write(b', "journeys_today": ')
        raw.write(str(self.journeys_today).encode("ascii"))
        raw.write(b', "journal_entries_in_history_today": ')
        raw.write(str(self.journal_entries_in_history_today).encode("ascii"))
        raw.write(b', "has_oseh_plus": ')
        raw.write(str(int(self.has_oseh_plus)).encode("ascii"))
        raw.write(b', "platform": "')
        raw.write(self.platform.encode("ascii"))
        raw.write(b'"}')

        return base64.urlsafe_b64encode(hashlib.sha256(raw.getvalue()).digest())

    def to_predicate_context(self) -> CheckFlowPredicateContext:
        return CheckFlowPredicateContext(
            user_tz=Wrapped(pytz.timezone("America/Los_Angeles")),
            last_journey_rating=Wrapped(self.last_journey_rating),
            journeys_today=Wrapped(self.journeys_today),
            journal_entries_in_history_today=Wrapped(
                self.journal_entries_in_history_today
            ),
        )

    def to_predicate_params(self) -> ClientFlowPredicateParams:
        return {
            "version": self.version,
            "queued_at": self.now,
            "account_created_at": self.account_created_at,
            "now": self.now,
            "user_sub": "oseh_u_placeholder",
            "ctx": self.to_predicate_context(),
        }


async def evict(itgs: Itgs, /):
    """Evicts all cached analysis results from redis. This should be called wheneever
    a client flow or client screen changes.
    """
    redis = await itgs.redis()
    await redis.incr(b"client_flow_graph_analysis:version")


@dataclass
class ClientFlowAnalysisLock:
    """Information about a client flow graph analysis lock."""

    graph: ClientFlowAnalysisEnvironment
    """The environment that this lock is for"""
    graph_id: bytes
    """The graph ID that this lock is for"""
    version: int
    """The overall version key that is incremented whenever we need to bust the
    cache at the time this lock was created
    """
    data_uid: bytes
    """The unique identifier for the data this lock is holding"""
    data_initialized_at: int
    """When this lock was acquired in seconds since the epoch (floored)"""
    data_expires_at: int
    """The latest the data guarded by this lock will expire in seconds since the epoch"""
    lock_type: Literal["reader", "writer"]
    """The type of lock this is"""
    lock_uid: bytes
    """The unique identifier for this lock"""
    lock_expires_at: int
    """The lock automatically expires after this time in seconds since the epoch"""


@dataclass
class ClientFlowAnalysisAcquireLockSuccess:
    type: Literal["success"]
    """
    - success: The lock was successfully acquired
    """
    lock: ClientFlowAnalysisLock
    """The lock that was acquired"""


@dataclass
class ClientFlowAnalysisAcquireLockAlreadyLocked:
    type: Literal["already_locked"]
    """
    - already_locked: The lock could not be acquired because it was already locked
    """


ClientFlowAnalysisAcquireWriteLockResult = Union[
    ClientFlowAnalysisAcquireLockSuccess, ClientFlowAnalysisAcquireLockAlreadyLocked
]


async def try_acquire_write_lock(
    itgs: Itgs, /, *, graph: ClientFlowAnalysisEnvironment, now: float
) -> ClientFlowAnalysisAcquireWriteLockResult:
    """Acquires a lock for writing to the given graph, if possible to do
    so. This never blocks or retries.

    This will emit the appropriate event to the pubsub system.

    Args:
        itgs (Itgs): the integrations to (re)use
        graph (ClientFlowAnalysisEnvironment): the environment to analyze
        now (float): the real current time in seconds since the epoch
    """
    graph_id = graph.to_redis_identifier()
    data_uid_if_initialize = f"oseh_cfga_{secrets.token_urlsafe(16)}".encode("ascii")
    lock_uid_if_acquired = f"oseh_cfgawl_{secrets.token_urlsafe(16)}".encode("ascii")
    now_floor = int(now)

    result = await safe_client_flow_graph_analysis_acquire_write_lock(
        itgs,
        graph_id=graph_id,
        uid_if_initialize=data_uid_if_initialize,
        lock_uid_if_acquired=lock_uid_if_acquired,
        now=now_floor,
        min_ttl=60,
    )
    if result.type == "initialized" or result.type == "replaced_stale":
        return ClientFlowAnalysisAcquireLockSuccess(
            type="success",
            lock=ClientFlowAnalysisLock(
                graph=graph,
                graph_id=graph_id,
                version=result.version,
                data_uid=data_uid_if_initialize,
                data_initialized_at=now_floor,
                data_expires_at=result.expires_at,
                lock_type="writer",
                lock_uid=lock_uid_if_acquired,
                lock_expires_at=result.stale_at,
            ),
        )
    if result.type == "existing_success":
        return ClientFlowAnalysisAcquireLockSuccess(
            type="success",
            lock=ClientFlowAnalysisLock(
                graph=graph,
                graph_id=graph_id,
                version=result.version,
                data_uid=result.data_uid,
                data_initialized_at=result.initialized_at,
                data_expires_at=result.expires_at,
                lock_type="writer",
                lock_uid=lock_uid_if_acquired,
                lock_expires_at=result.stale_at,
            ),
        )
    assert result.type == "existing_locked", result
    return ClientFlowAnalysisAcquireLockAlreadyLocked(type="already_locked")


@dataclass
class ClientFlowAnalysisAcquireLockNotFound:
    type: Literal["not_found"]
    """
    - not_found: The reader lock could not be acquired because the corresponding data does
        not exist (and thus there is nothing for the reader lock to guard)
    """


ClientFlowAnalysisAcquireReadLockResult = Union[
    ClientFlowAnalysisAcquireLockSuccess,
    ClientFlowAnalysisAcquireLockAlreadyLocked,
    ClientFlowAnalysisAcquireLockNotFound,
]


async def try_acquire_read_lock(
    itgs: Itgs, /, *, graph: ClientFlowAnalysisEnvironment, now: float
) -> ClientFlowAnalysisAcquireReadLockResult:
    """Acquires a lock for reading the given graph, if possible to do so.
    This never blocks or retries.

    This will emit the appropriate event to the pubsub system.

    Args:
        itgs (Itgs): the integrations to (re)use
        graph (ClientFlowAnalysisEnvironment): the environment to analyze
        now (float): the real current time in seconds since the epoch
    """

    graph_id = graph.to_redis_identifier()
    lock_uid_if_acquired = f"oseh_cfgawl_{secrets.token_urlsafe(16)}".encode("ascii")
    now_floor = int(now)

    result = await safe_client_flow_graph_analysis_acquire_read_lock(
        itgs,
        graph_id=graph_id,
        lock_uid_if_acquired=lock_uid_if_acquired,
        now=now_floor,
        min_ttl=10,
    )
    if result.type == "stale" or result.type == "not_found":
        return ClientFlowAnalysisAcquireLockNotFound(type="not_found")

    if result.type == "existing_locked":
        return ClientFlowAnalysisAcquireLockAlreadyLocked(type="already_locked")

    return ClientFlowAnalysisAcquireLockSuccess(
        type="success",
        lock=ClientFlowAnalysisLock(
            graph=graph,
            graph_id=graph_id,
            version=result.version,
            data_uid=result.data_uid,
            data_initialized_at=result.initialized_at,
            data_expires_at=result.expires_at,
            lock_type="reader",
            lock_uid=lock_uid_if_acquired,
            lock_expires_at=result.stale_at,
        ),
    )


@dataclass
class ClientFlowAnalysisReleaseLockSuccess:
    type: Literal["success"]
    """
    - success: The lock was successfully released
    """


@dataclass
class ClientFlowAnalysisReleaseLockNotHeld:
    type: Literal["not_held"]
    """
    - not_held: The lock was not held anymore.
    """


ClientFlowAnalysisReleaseLockResult = Union[
    ClientFlowAnalysisReleaseLockSuccess, ClientFlowAnalysisReleaseLockNotHeld
]


async def try_release_lock(
    itgs: Itgs, /, *, lock: ClientFlowAnalysisLock, now: float
) -> ClientFlowAnalysisReleaseLockResult:
    """Releases the lock for reading or writing to the given graph, if it is still
    held by us.

    This will emit the appropriate event to the pubsub system.

    Args:
        itgs (Itgs): the integrations to (re)use
        lock (ClientFlowAnalysisLock): the lock to release
        now (float): the real current time in seconds since the epoch
    """
    if lock.lock_type == "reader":
        return await try_release_read_lock(itgs, lock=lock, now=now)
    elif lock.lock_type == "writer":
        return await try_release_write_lock(itgs, lock=lock, now=now)
    else:
        raise ValueError(f"Unknown lock type {lock}")


async def try_release_write_lock(
    itgs: Itgs, /, *, lock: ClientFlowAnalysisLock, now: float
) -> ClientFlowAnalysisReleaseLockResult:
    """Releases the lock for writing to the given graph, if it is still
    held by us.

    This will emit the appropriate event to the pubsub system.

    Args:
        itgs (Itgs): the integrations to (re)use
        lock (ClientFlowAnalysisLock): the lock to release
        now (float): the real current time in seconds since the epoch
    """
    assert lock.lock_type == "writer", "This lock is not a write lock"
    result = await safe_client_flow_graph_analysis_release_write_lock(
        itgs, graph_id=lock.graph_id, version=lock.version, lock_uid=lock.lock_uid
    )
    if result.type == "success":
        return ClientFlowAnalysisReleaseLockSuccess(type="success")
    if result.type == "lock_lost":
        return ClientFlowAnalysisReleaseLockNotHeld(type="not_held")
    raise ValueError(f"Unknown result type {result}")


async def try_release_read_lock(
    itgs: Itgs, /, *, lock: ClientFlowAnalysisLock, now: float
) -> ClientFlowAnalysisReleaseLockResult:
    """Releases the lock for reading the given graph, if it is still held
    by us.

    Args:
        itgs (Itgs): the integrations to (re)use
        lock (ClientFlowAnalysisLock): the lock to release
        now (float): the real current time in seconds since the epoch
    """
    assert lock.lock_type == "reader", "This lock is not a read lock"
    result = await safe_client_flow_graph_analysis_release_read_lock(
        itgs,
        graph_id=lock.graph_id,
        version=lock.version,
        lock_uid=lock.lock_uid,
        now=int(now),
    )
    if result.type == "success":
        return ClientFlowAnalysisReleaseLockSuccess(type="success")
    if result.type == "lock_lost":
        return ClientFlowAnalysisReleaseLockNotHeld(type="not_held")
    raise ValueError(f"Unknown result type {result}")


class FlowPathNodeEdgeViaScreenTrigger(BaseModel):
    type: Literal["screen-trigger"] = Field(
        description=(
            "- `screen-trigger`: indicates that this edge was found via the allowed triggers "
            "on a screen in the previous flow, and we were able to find a screen parameter "
            "matching this trigger in the fixed screen parameters\n"
        )
    )
    index: int = Field(description="The index of the screen within the previous flow")
    slug: str = Field(
        description="The slug of the screen at this index within the previous flow"
    )
    name: Optional[str] = Field(
        description="If a name was set on the screen within the previous flow, the name, otherwise None"
    )
    trigger: List[Union[str, int]] = Field(
        description="The path to the flow_slug trigger in the fixed screen parameters"
    )
    description: str = Field(
        description="The best description we could find for when this trigger occurs, e.g. "
        "'How to handle the back button'. This is pulled from the documentation of the "
        "trigger parameter or a parent and thus is usually written for what to fill in for "
        "the value"
    )


class FlowPathNodeEdgeViaScreenAllowed(BaseModel):
    type: Literal["screen-allowed"] = Field(
        description=(
            "- `screen-allowed`: indicates that this edge was found via the allowed screens "
            "on the flow and we were unable to find more specific information about the edge\n"
        )
    )
    index: int = Field(description="The index of the screen within the flow")
    slug: str = Field(
        description="The slug of the screen at this index within the flow"
    )
    name: Optional[str] = Field(
        description="If a name was set on the screen within the previous flow, the name, otherwise None"
    )


class FlowPathNodeEdgeViaFlowReplacerRule(BaseModel):
    type: Literal["flow-replacer-rule"] = Field(
        description=(
            "- `flow-replacer-rule`: indicates that this edge was found via a flow replacer rule\n"
        )
    )
    rule_index: int = Field(description="The index of the rule within the flow")


FlowPathNodeEdgeVia = Union[
    FlowPathNodeEdgeViaScreenTrigger,
    FlowPathNodeEdgeViaScreenAllowed,
    FlowPathNodeEdgeViaFlowReplacerRule,
]


class FlowPathNode(BaseModel):
    type: Literal["edge"] = Field(
        description=(
            "- `edge`: describes an edge in the path. For the first edge, the previous flow is the "
            "source indicated in the key. For all other edges, the source is the flow from the "
            "previous edge.\n"
        )
    )
    via: FlowPathNodeEdgeVia = Field(description="How this edge was found")
    slug: str = Field(description="The slug of the flow reached")


class FlowPath(BaseModel):
    """Describes a path from one flow to another"""

    type: Literal["path"] = Field(
        description="- `path`: describes a path from one flow to another\n"
    )
    nodes: List[FlowPathNode] = Field(description="The nodes in the path")


class FlowDone(BaseModel):
    """Indicates all the paths have been enumerated"""

    type: Literal["done"] = Field(
        description="- `done`: indicates all the paths have been enumerated\n"
    )


FLOW_DONE_SERIALIZED = b'{"type":"done"}'


FlowPathOrDone = Union[FlowPath, FlowDone]
flow_path_or_done_adapter = cast(
    TypeAdapter[FlowPathOrDone], TypeAdapter(FlowPathOrDone)
)


@dataclass
class PeekedFlowPaths:
    """When reading reachable flows, we read the first path as an example
    for how the two flows are connected, plus the number of paths found
    """

    count: int
    """How many paths were found connecting the source to the target. This
    does not count FlowDone and thus may be 0
    """
    first: FlowPathOrDone
    """The first path in the list to serve as an example. Should always be
    a flow path if things aren't corrupted, though we keep the type expansive
    in case for some reason we have zero node paths in the future
    """


@dataclass
class ReachableFlows:
    """A page within a reachable (or inverted reachable) analysis."""

    items: Dict[str, PeekedFlowPaths]
    """The items within this batch, where the keys are client flow slugs
    that are reachable from the source, and the values are different
    paths from the source to that key. This dictionary may be empty.

    For example, on a normal reachability analysis, if the source slug
    is `a` and the result is `{"b": [["a", "c", "b"], ["a", "d", "e", "b"]]}` (simplifying
    the path nodes to just slugs), then that means b is reachable from a (since
    its a key), and it can be reached via two paths:
    - a -> c -> b
    - a -> d -> e -> b
    """

    cursor: Optional[int]
    """The cursor to use for the next scan request, or None if the end has been reached"""


@dataclass
class ReachableFlowsResultSuccess:
    """Indicates we were able to get one page from a reachable (or inverted reachable) analysis."""

    type: Literal["success"]
    """
    - success: The operation was successful
    """
    flows: ReachableFlows
    """The reachable flows"""


@dataclass
class ReachableFlowsResultNotInitialized:
    """Indicates that the analysis has not been initialized yet (or was written to only partially,
    as detected via a missing __computed__ node)
    """

    type: Literal["not_initialized"]
    """
    - not_initialized: The analysis has not been initialized yet
    """


@dataclass
class ReachableFlowsResultLockLost:
    """Indicates that you no longer hold the indicated lock"""

    type: Literal["lock_lost"]
    """
    - lock_lost: The lock was lost
    """


ReachableFlowsResult = Union[
    ReachableFlowsResultSuccess,
    ReachableFlowsResultNotInitialized,
    ReachableFlowsResultLockLost,
]


async def try_read_reachable_flows_page_from_cache(
    itgs: Itgs,
    /,
    *,
    lock: ClientFlowAnalysisLock,
    source: str,
    cursor: int,
    max_steps: Optional[int],
    inverted: bool,
    now: int,
) -> ReachableFlowsResult:
    """Attempts to read the already initialized reachable flows (within the given number of steps)
    from the cache.

    Given the graph:

    ```
    a -> b -> c
    a -> d -> e
    ```

    then the following results are possible:

    reachable from source=a, max_steps=1, inverted=False
    ```json
    {
        "b": [["a", "b"]],
        "d": [["a", "d"]]
    }
    ```

    reachable from source=a, max_steps=2, inverted=False
    ```json
    {
        "b": [["a", "b"]],
        "c": [["a", "b", "c"]],
        "d": [["a", "d"]],
        "e": [["a", "d", "e"]]
    }
    ```

    reachable from source=a, max_steps=1, inverted=True
    `{}`

    reachable from source=c, max_steps=1, inverted=True
    ```json
    {
        "b": [["c", "b"]]
    }
    ```


    Args:
        itgs (Itgs): the integrations to (re)use
        lock (ClientFlowAnalysisLock): the lock to use
        source (str): the source client flow slug
        cursor (int): the cursor to use for the next scan request, or 0 if the start
        max_steps (Optional[int]): the maximum number of steps to consider, or None for no limit
        inverted (bool): False to use the original graph, True to use the inverted graph. If False,
            the result helps answer the question "where can I go from the source?", and if True, it
            helps answer the question "how do I get to the source?". Make sure to invert the returned
            paths before displaying to the user if inverted is True.
    """
    result = await safe_client_flow_graph_analysis_read_reachable(
        itgs,
        graph_id=lock.graph_id,
        version=lock.version,
        lock_type=lock.lock_type,
        lock_uid=lock.lock_uid,
        source_flow_slug=source.encode("utf-8"),
        inverted=inverted,
        now=now,
        cursor=cursor,
        max_steps=max_steps,
    )
    if result.type == "success":
        items: Dict[str, PeekedFlowPaths] = {}
        for item in result.flow_items:
            items[item.slug.decode("utf-8")] = PeekedFlowPaths(
                count=item.count,
                first=flow_path_or_done_adapter.validate_json(item.first),
            )
        return ReachableFlowsResultSuccess(
            type="success", flows=ReachableFlows(items=items, cursor=result.cursor)
        )

    if result.type == "not_found":
        return ReachableFlowsResultNotInitialized(type="not_initialized")

    if result.type == "lock_lost":
        return ReachableFlowsResultLockLost(type="lock_lost")

    if result.type == "corrupted":
        await handle_warning(
            f"{__name__}:corrupted_reachable_flows",
            "Detected invariant violation in:\n\n"
            f"```\n{lock.graph_id=}\n{lock.version=}\n{lock.lock_type=}\n{lock.lock_uid=}\n{lock.data_uid=}\n{lock.data_initialized_at=}\n{lock.data_expires_at=}\n{lock.lock_expires_at=}\n{source=}\n{cursor=}\n{max_steps=}\n{inverted=}\n```\n\nrecovering by evicting",
        )
        await evict(itgs)
        return ReachableFlowsResultSuccess(
            type="success", flows=ReachableFlows(items={}, cursor=None)
        )

    raise ValueError(f"Unknown result type {result}")


@dataclass
class TransferReachableFlowsFromDBResultSuccess:
    """Indicates that the transfer was successful"""

    type: Literal["success"]
    """
    - success: The operation was successful
    """


@dataclass
class TransferReachableFlowsFromDBResultLockLost:
    """Indicates that you no longer hold the indicated lock"""

    type: Literal["lock_lost"]
    """
    - lock_lost: The lock was lost
    """


TransferReachableFlowsFromDBResult = Union[
    TransferReachableFlowsFromDBResultSuccess,
    TransferReachableFlowsFromDBResultLockLost,
]


async def transfer_reachable_flows_from_db(
    itgs: Itgs,
    /,
    *,
    lock: ClientFlowAnalysisLock,
    source: str,
    max_steps: Optional[int],
    inverted: bool,
) -> TransferReachableFlowsFromDBResult:
    """Reads the reachable flows (within the given number of steps) from the database,
    reusing helpful information already stored, transfering that information into the
    cache. This generally does not require loading all the data into memory at once,
    and hence does not return anything to leave the maximum amount of flexibility
    for the implementation.

    In the worst case, with unlimited max steps, this may require visiting every vertex.

    Requires a write lock and that the data is not already initialized (or was only partially
    written by the previous holder). This will only write while the lock is held, meaning if
    the lock is lost midway through, only some data will be written (this is
    perfectly detectable and recoverable; it will been seen as if it were uninitialized)

    Args: see `try_read_reachable_flows_page_from_cache`
    """
    assert lock.lock_type == "writer", "This lock is not a write lock"

    if max_steps == 1 and not inverted:
        return await _transfer_adjacency_list_from_db(itgs, lock=lock, source=source)
    if max_steps == 1 and inverted:
        return await _transfer_inverted_adjacency_list_from_db(
            itgs, lock=lock, source=source
        )

    return await _transfer_extended_paths_from_db(
        itgs,
        lock=lock,
        source=source,
        inverted=inverted,
        max_steps=max_steps,
    )


@dataclass
class ReadPathsPageResultSuccess:
    type: Literal["success"]
    """
    - `success`: the required analysis is in the cache. there are paths between
        the source and the target as indicated. returns the page (from the offset
        and limit), which may be empty.
    """
    page: List[FlowPathOrDone]
    """The items on this page."""


@dataclass
class ReadPathsPageResultNoPaths:
    type: Literal["no_paths"]
    """
    - `no_paths`: the required analysis is in the cache, but there are no paths
    """


@dataclass
class ReadPathsPageResultNotFound:
    type: Literal["not_found"]
    """
    - `not_found`: the requested data is not in the cache
    """


@dataclass
class ReadPathsPageResultLockLost:
    type: Literal["lock_lost"]
    """
    - `lock_lost`: the lock was lost
    """


ReadPathsPageResult = Union[
    ReadPathsPageResultSuccess,
    ReadPathsPageResultNoPaths,
    ReadPathsPageResultNotFound,
    ReadPathsPageResultLockLost,
]


async def read_paths_page_from_cache(
    itgs: Itgs,
    /,
    *,
    lock: ClientFlowAnalysisLock,
    source: str,
    target: str,
    max_steps: Optional[int],
    inverted: bool,
    offset: int,
    limit: int,
    now: int,
) -> ReadPathsPageResult:
    """
    Reads up to the given limit of items, skipping the first offset items, from
    the cached list of paths from the source to the target within the given
    maximum numebr of steps.

    Typically, iteration would continue from after the first entry returned from
    try_read_reachable_flows_page_from_cache and continue until FlowDone is
    received.

    The limit is fetched in a single redis call, and thus should stay small
    (e.g., less than 10). Often it makes sense to return more items for an API
    query, in which case you should repeatedly call this with the smaller limit
    until you are satisfied with the number of items. Technically, this is an
    O(N^2) operation within redis as LRANGE requires time linear to the offset,
    but the pointer walking is fast enough that it is unlikely to be an issue at
    the lengths expected, compared to the time spent by redis serializing and sending
    the response.

    Args:
        itgs (Itgs): the integrations to (re)use
        lock (ClientFlowAnalysisLock): the lock to use. may be writer or reader
        source (str): the source client flow slug
        target (str): the target client flow slug
        max_steps (int, None): the maximum number of steps from the source in the returned
            path (e.g., 1 means only paths that are direct). None for unlimited steps.
        inverted (bool): False to use the original graph, True to use the inverted graph.
            If False, the result is paths from source to target. If True, the result is paths
            from target to source. Note that when True, the paths should be reversed before
            displaying to the user.
        offset (int): the number of items to skip before returning (semantics and
            performance equivalent to LRANGE's start)
        limit (int): the maximum number of items to return
        now (int): the current time in seconds since the epoch

    Returns:
        ReadPathsPageResult: the result of the operation
    """
    result = await safe_client_flow_graph_analysis_read_paths_page(
        itgs,
        graph_id=lock.graph_id,
        version=lock.version,
        lock_type=lock.lock_type,
        lock_uid=lock.lock_uid,
        source=source.encode("utf-8"),
        target=target.encode("utf-8"),
        inverted=inverted,
        max_steps=max_steps,
        offset=offset,
        limit=limit,
        now=now,
    )
    if result.type == "success":
        return ReadPathsPageResultSuccess(
            type="success",
            page=[
                flow_path_or_done_adapter.validate_json(item) for item in result.page
            ],
        )
    if result.type == "no_paths":
        return ReadPathsPageResultNoPaths(type="no_paths")
    if result.type == "not_found":
        return ReadPathsPageResultNotFound(type="not_found")
    if result.type == "lock_lost":
        return ReadPathsPageResultLockLost(type="lock_lost")
    if result.type == "corrupted":
        await handle_warning(
            f"{__name__}:read_paths_page:corrupted",
            f"Detected invariant violation during read in:\n\n"
            f"```\n{lock.graph_id=}\n{lock.version=}\n{lock.lock_type=}\n{lock.lock_uid=}\n{lock.data_uid=}\n{lock.data_initialized_at=}\n{lock.data_expires_at=}\n{lock.lock_expires_at=}\n{source=}\n{target=}\n{max_steps=}\n{inverted=}\n{offset=}\n{limit=}\n```\n\nrecovering by evicting",
        )
        await evict(itgs)
        return ReadPathsPageResultSuccess(type="success", page=[])
    raise ValueError(f"Unknown result type {result}")


async def _transfer_from_iterator(
    itgs: Itgs,
    /,
    *,
    lock: ClientFlowAnalysisLock,
    source: str,
    inverted: bool,
    max_steps: Optional[int],
    iter: Union[
        AsyncIterator[Tuple[bytes, FlowPathOrDone]],
        AsyncIterator[TransferReachableFlowsFromDBResult],
        AsyncIterator[
            Union[Tuple[bytes, FlowPathOrDone], TransferReachableFlowsFromDBResult]
        ],
    ],
) -> TransferReachableFlowsFromDBResult:
    """If the iterator yields a batch result, any pending writes are aborted and the value
    is returned immediately. Otherwise, we pull items from the iterator and batch them
    together, occassionally writing to the cache. The iterator may not be completely
    consumed if, for example, the lock is lost.

    It generally doesn't make sense for the iterator to yield
    ClientFlowGraphAnalysisWriteBatchResultSuccess, but it can make sense to
    yield the various failure types.
    """
    assert lock.lock_type == "writer", "This lock is not a write lock"

    source_bytes = source.encode("utf-8")
    paths_per_redis_batch = 10

    redis_batch: Dict[bytes, List[bytes]] = dict()
    redis_batch_num_paths = 0

    async def _write_batch(
        is_first: bool, is_last: bool
    ) -> ClientFlowGraphAnalysisWriteBatchResult:
        nonlocal redis_batch_num_paths

        formatted_batch: List[bytes] = []
        formatted_batch.append(str(len(redis_batch)).encode("ascii"))
        for target, paths in redis_batch.items():
            formatted_batch.append(target)
            formatted_batch.append(str(len(paths)).encode("ascii"))
            formatted_batch.extend(paths)

        result = await safe_client_flow_graph_analysis_write_batch(
            itgs,
            graph_id=lock.graph_id,
            version=lock.version,
            lock_uid=lock.lock_uid,
            inverted=inverted,
            source=source_bytes,
            max_steps=max_steps,
            is_first=is_first,
            is_last=is_last,
            batch=formatted_batch,
        )

        redis_batch_num_paths = 0
        redis_batch.clear()
        return result

    wrote_first = False
    async for iter_yielded in iter:
        if not isinstance(iter_yielded, tuple):
            return iter_yielded
        target_flow, item = iter_yielded
        if redis_batch_num_paths >= paths_per_redis_batch:
            res = await _write_batch(is_first=not wrote_first, is_last=False)
            if res.type == "lock_lost":
                return TransferReachableFlowsFromDBResultLockLost(type="lock_lost")
            if res.type == "corrupted":
                await handle_warning(
                    f"{__name__}:corrupted_reachable_flows:batch",
                    f"Detected invariant violation during write in:\n\n"
                    f"```\n{lock.graph_id=}\n{lock.version=}\n{lock.lock_type=}\n{lock.lock_uid=}\n{lock.data_uid=}\n{lock.data_initialized_at=}\n{lock.data_expires_at=}\n{lock.lock_expires_at=}\n{source=}\n```\n\nrecovering by evicting",
                )
                await evict(itgs)
                return TransferReachableFlowsFromDBResultSuccess(type="success")
            assert res.type == "success", res
            wrote_first = True

        curr_list = redis_batch.get(target_flow)
        if curr_list is None:
            curr_list = []
            redis_batch[target_flow] = curr_list
        curr_list.append(
            FLOW_DONE_SERIALIZED
            if item.type == "done"
            else FlowPath.__pydantic_serializer__.to_json(item)
        )
        redis_batch_num_paths += 1

    res = await _write_batch(is_first=not wrote_first, is_last=True)
    if res.type == "lock_lost":
        return TransferReachableFlowsFromDBResultLockLost(type="lock_lost")
    if res.type == "corrupted":
        await handle_warning(
            f"{__name__}:corrupted_reachable_flows:final",
            f"Detected invariant violation during write in:\n\n"
            f"```\n{lock.graph_id=}\n{lock.version=}\n{lock.lock_type=}\n{lock.lock_uid=}\n{lock.data_uid=}\n{lock.data_initialized_at=}\n{lock.data_expires_at=}\n{lock.lock_expires_at=}\n{source=}\n```\n\nrecovering by evicting",
        )
        await evict(itgs)
        return TransferReachableFlowsFromDBResultSuccess(type="success")
    assert res.type == "success", res
    return TransferReachableFlowsFromDBResultSuccess(type="success")


async def _no_paths() -> AsyncIterator[Tuple[bytes, FlowPathOrDone]]:
    if False:
        yield (b"", FlowDone(type="done"))


async def _transfer_adjacency_list_from_db(
    itgs: Itgs,
    /,
    *,
    lock: ClientFlowAnalysisLock,
    source: str,
) -> TransferReachableFlowsFromDBResult:
    """Transfers the adjacency list (all flows reachable in the normal graph from
    the source in one step) to the cache. This relies on the db directly; longer
    paths may use this value rather than reaching to the database directly

    PERF: Originally this hit the db directly without a cache and it was a significant
    slowdown to do it that way when processing many different environments (common on
    e.g. delete prechecks for the flow)

    Args:
        itgs (Itgs): the integrations to (re)use
        lock (ClientFlowAnalysisLock): the lock to use
        source (str): the source client flow slug
    """
    assert lock.lock_type == "writer", "This lock is not a write lock"

    flow = await get_client_flow(itgs, slug=source, minimal=False)
    return await _transfer_from_iterator(
        itgs,
        lock=lock,
        source=source,
        inverted=False,
        max_steps=1,
        iter=(
            _no_paths()
            if flow is None
            else _iterate_adjacent_flows(
                itgs,
                graph=lock.graph,
                source_slug=source,
                source_screens=flow.screens,
                source_rules=flow.rules,
            )
        ),
    )


async def _transfer_inverted_adjacency_list_from_db(
    itgs: Itgs,
    /,
    *,
    lock: ClientFlowAnalysisLock,
    source: str,
) -> TransferReachableFlowsFromDBResult:
    return await _transfer_from_iterator(
        itgs,
        lock=lock,
        source=source,
        inverted=True,
        max_steps=1,
        iter=_find_and_iterate_inverted_adjacent_flows(
            itgs,
            lock=lock,
            source=source,
        ),
    )


async def _find_and_iterate_inverted_adjacent_flows(
    itgs: Itgs,
    /,
    *,
    lock: ClientFlowAnalysisLock,
    source: str,
) -> AsyncIterator[
    Union[Tuple[bytes, FlowPathOrDone], TransferReachableFlowsFromDBResult]
]:
    """Returns the edges from the source in the inverted graph, i.e., all the edges
    to the source in the normal graph. This will fill the entire adjacency list of the
    normal graph in order to discover which flows can reach the source in a single step.

    PERF:
        May help reduce database leader load to cache all the slugs available, but would
        need to be careful of cache busting. It's also an index-only in-order read in batches,
        so it's not that much load (probably dominated by serialization overhead).
    """
    assert lock.lock_type == "writer", "This lock is not a write lock"

    source_bytes = source.encode("utf-8")
    redis_read_batch_size = 10

    flow_slugs = list(await get_valid_client_flow_slugs(itgs))

    await itgs.ensure_redis_liveliness()
    redis = await itgs.redis()

    for row_slug in flow_slugs:
        row_slug_bytes = row_slug.encode("utf-8")

        adjacency_list_available = await redis.sismember(
            b"client_flow_graph_analysis:"
            + lock.data_uid
            + b":reachable:"
            + row_slug_bytes
            + b":1",  # type: ignore
            b"__computed__",  # type: ignore
        )
        if not adjacency_list_available:
            sub_result = await _transfer_adjacency_list_from_db(
                itgs, lock=lock, source=row_slug
            )
            if sub_result.type != "success":
                yield sub_result
                return

        paths_to_me_key = (
            b"client_flow_graph_analysis:"
            + lock.data_uid
            + b":reachable:"
            + row_slug_bytes
            + b":1:paths:"
            + source_bytes
        )
        paths_to_me_batch = cast(
            List[bytes],
            await redis.lrange(
                paths_to_me_key, 0, redis_read_batch_size - 1  # type: ignore
            ),
        )
        if not paths_to_me_batch:
            # no path from source to me
            continue

        read_up_to_excl = redis_read_batch_size
        while True:
            seen_done = False
            for path_raw in paths_to_me_batch:
                if seen_done:
                    await handle_warning(
                        f"{__name__}:inverted_adjacency_list:forward_list_done_not_last",
                        f"Detected invariant violation in:\n\n"
                        f"```\n{lock.graph_id=}\n{lock.version=}\n{lock.lock_type=}\n{lock.lock_uid=}\n{lock.data_uid=}\n{lock.data_initialized_at=}\n{lock.data_expires_at=}\n{lock.lock_expires_at=}\n{source=}\n{row_slug=}\n```\n\nrecovering by evicting",
                    )
                    await evict(itgs)
                    return
                path = flow_path_or_done_adapter.validate_json(path_raw)
                if path.type == "done":
                    seen_done = True
                    yield row_slug_bytes, path
                else:
                    yield row_slug_bytes, FlowPath(
                        type="path",
                        nodes=list(reversed(path.nodes)),
                    )

            if seen_done:
                break

            if len(paths_to_me_batch) != redis_read_batch_size:
                await handle_warning(
                    f"{__name__}:inverted_adjacency_list:forward_list_missing_done",
                    f"Detected invariant violation in:\n\n"
                    f"```\n{lock.graph_id=}\n{lock.version=}\n{lock.lock_type=}\n{lock.lock_uid=}\n{lock.data_uid=}\n{lock.data_initialized_at=}\n{lock.data_expires_at=}\n{lock.lock_expires_at=}\n{source=}\n{row_slug=}\n```\n\nrecovering by evicting",
                )
                await evict(itgs)
                return

            paths_to_me_batch = cast(
                List[bytes],
                await redis.lrange(
                    paths_to_me_key,  # type: ignore
                    read_up_to_excl,
                    read_up_to_excl + redis_read_batch_size - 1,
                ),
            )
            read_up_to_excl += redis_read_batch_size
            if not paths_to_me_batch:
                await handle_warning(
                    f"{__name__}:inverted_adjacency_list:forward_list_missing_done",
                    f"Detected invariant violation in:\n\n"
                    f"```\n{lock.graph_id=}\n{lock.version=}\n{lock.lock_type=}\n{lock.lock_uid=}\n{lock.data_uid=}\n{lock.data_initialized_at=}\n{lock.data_expires_at=}\n{lock.lock_expires_at=}\n{source=}\n{row_slug=}\n```\n\nrecovering by evicting",
                )
                await evict(itgs)
                return


async def _transfer_extended_paths_from_db(
    itgs: Itgs,
    /,
    *,
    lock: ClientFlowAnalysisLock,
    source: str,
    inverted: bool,
    max_steps: Optional[int],
) -> TransferReachableFlowsFromDBResult:
    return await _transfer_from_iterator(
        itgs,
        lock=lock,
        source=source,
        inverted=inverted,
        max_steps=max_steps,
        iter=_iterate_extended_paths(
            itgs,
            lock=lock,
            source=source,
            inverted=inverted,
            max_steps=max_steps,
        ),
    )


async def _iterate_extended_paths(
    itgs: Itgs,
    /,
    *,
    lock: ClientFlowAnalysisLock,
    source: str,
    inverted: bool,
    max_steps: Optional[int],
) -> AsyncIterator[
    Union[Tuple[bytes, FlowPathOrDone], TransferReachableFlowsFromDBResult]
]:
    """Walks the graph until all leafs are expired or the maximum number of steps
    is reached, writing all the found paths to the cache. This is not guarranteed
    to be exhaustive for all paths, but it is guarranteed to find at least one path
    between the source and any reachable target. Only paths which differ in "interesting"
    ways are included.

    Here is an example of how this works:
        `A -> B -> C -> D` would be kept as its a novel way to get to D
        `A -> E -> B -> C -> D` would be eliminated because we already showed a way to D via B
        `A -> F -> D` would be kept as its a novel way to get to D

    This handles cycles by discarding paths with repeated nodes. Note that adjacency
    lists may have repeated nodes (only in the case of a loop, i.e., A -> A), so this
    is a special property for n != 1. Hence, it's possible for the number of paths n=1
    to be larger than n=None (if the only path from the node is a loop)

    This only takes the first path in the adjacency list, discarding repeats
    (e.g., the multigraph is reduced to a graph), mostly because it's assumed
    not to be very helpful when looking at multiple steps.

    For the required adjacency lists this will use the cache; if a node is discovered
    and needs to be walked but is not in the cache, it will be written to the cache

    This does not write lower steps to the cache (with the exception of
    adjacency lists), i.e., for maximum steps 3, it will not fill the cache for
    maximum steps 2. Similarly, it will not fill higher steps, i.e., for maximum
    steps 3, it will not fill the cache for maximum steps 4. This is to avoid
    writing too much data to the cache, especially under the assumption the
    maximum steps is probably just chosen as a small reasonable value to keep
    the interface snappy and switched to None with a warning if that isn't
    enough

    Args:
        itgs (Itgs): the integrations to (re)use
        lock (ClientFlowAnalysisLock): the lock to use
        source (str): the source client flow slug
        inverted (bool): False to use the original graph, True to use the inverted graph
        max_steps (Optional[int]): the maximum number of steps to consider, or None for no limit
    """
    assert (
        max_steps is None or max_steps > 1
    ), "this can only write extended paths, not adjacency lists"

    open_targets: Set[str] = set()

    queue = deque([(source, cast(List[FlowPathNode], []))])
    while queue:
        current_slug, path_to_current_slug = queue.popleft()

        parts_in_current_path = frozenset(v.slug for v in path_to_current_slug)

        cursor = 0
        tried_initialize = False
        while cursor is not None:
            result = await try_read_reachable_flows_page_from_cache(
                itgs,
                lock=lock,
                source=current_slug,
                cursor=cursor,
                max_steps=1,
                inverted=inverted,
                now=int(time.time()),
            )
            if result.type == "lock_lost":
                yield TransferReachableFlowsFromDBResultLockLost(type="lock_lost")
                return
            if result.type == "not_initialized":
                assert cursor == 0, "only the first page can be uninitialized"
                assert not tried_initialize, "only initialize once"
                tried_initialize = True
                transfer_result = await transfer_reachable_flows_from_db(
                    itgs,
                    lock=lock,
                    source=current_slug,
                    max_steps=1,
                    inverted=inverted,
                )
                if transfer_result.type == "lock_lost":
                    yield TransferReachableFlowsFromDBResultLockLost(type="lock_lost")
                    return
                assert transfer_result.type == "success", transfer_result
                continue
            assert result.type == "success", result

            cursor = result.flows.cursor
            for target_slug, peeked in result.flows.items.items():
                if target_slug == source or target_slug in parts_in_current_path:
                    continue
                if peeked.first.type == "done":
                    continue
                assert (
                    len(peeked.first.nodes) == 1
                ), "only one node peeked adjacency list paths supported (for length detection)"

                new_nodes = path_to_current_slug + peeked.first.nodes
                yield target_slug.encode("utf-8"), FlowPath(
                    type="path",
                    nodes=new_nodes,
                )

                if target_slug in open_targets:
                    continue

                open_targets.add(target_slug)

                if max_steps is None or len(new_nodes) < max_steps:
                    queue.append((target_slug, new_nodes))

    for target in open_targets:
        yield target.encode("utf-8"), FlowDone(type="done")


async def _iterate_adjacent_flows(
    itgs: Itgs,
    /,
    *,
    graph: ClientFlowAnalysisEnvironment,
    source_slug: str,
    source_screens: List[ClientFlowScreen],
    source_rules: ClientFlowRules,
) -> AsyncIterator[Tuple[bytes, FlowPathOrDone]]:
    predicate_params = graph.to_predicate_params()
    for rule_index, rule in enumerate(source_rules):
        if await check_flow_predicate(itgs, rule.condition, **predicate_params):
            if rule.effect.type == "skip":
                return

            if rule.effect.type == "replace":
                slug_bytes = rule.effect.slug.encode("utf-8")
                if slug_bytes in IGNORE_FORWARD_TARGETS:
                    return

                yield slug_bytes, FlowPath(
                    type="path",
                    nodes=[
                        FlowPathNode(
                            type="edge",
                            via=FlowPathNodeEdgeViaFlowReplacerRule(
                                type="flow-replacer-rule",
                                rule_index=rule_index,
                            ),
                            slug=rule.effect.slug,
                        )
                    ],
                )
                yield slug_bytes, FlowDone(type="done")
                return

    for screen_index, screen in enumerate(source_screens):
        if screen.rules.trigger is not None and await check_flow_predicate(
            itgs, screen.rules.trigger, **predicate_params
        ):
            continue

        if screen.rules.peek is not None and await check_flow_predicate(
            itgs, screen.rules.peek, **predicate_params
        ):
            continue

        if (
            graph.platform == "android"
            and (screen.flags & ClientFlowScreenFlag.SHOWS_ON_ANDROID) == 0
        ):
            continue

        if (
            graph.platform == "ios"
            and (screen.flags & ClientFlowScreenFlag.SHOWS_ON_IOS) == 0
        ):
            continue

        if (
            graph.platform == "browser"
            and (screen.flags & ClientFlowScreenFlag.SHOWS_ON_WEB) == 0
        ):
            continue

        if (
            graph.has_oseh_plus
            and (screen.flags & ClientFlowScreenFlag.SHOWS_FOR_PRO) == 0
        ):
            continue

        if (
            not graph.has_oseh_plus
            and (screen.flags & ClientFlowScreenFlag.SHOWS_FOR_FREE) == 0
        ):
            continue

        shown_screen_meta = await get_client_screen(itgs, slug=screen.screen.slug)
        if shown_screen_meta is not None:
            if (
                graph.platform == "android"
                and (shown_screen_meta.flags & ClientScreenFlag.SHOWS_ON_ANDROID) == 0
            ):
                continue

            if (
                graph.platform == "ios"
                and (shown_screen_meta.flags & ClientScreenFlag.SHOWS_ON_IOS) == 0
            ):
                continue

            if (
                graph.platform == "browser"
                and (shown_screen_meta.flags & ClientScreenFlag.SHOWS_ON_BROWSER) == 0
            ):
                continue

        for allowed_slug in screen.allowed_triggers:
            allowed_slug_bytes = allowed_slug.encode("utf-8")
            if allowed_slug_bytes in IGNORE_FORWARD_TARGETS:
                continue

            found_candidate = False
            for path in _deep_search_value(screen.screen.fixed, allowed_slug):
                screen_meta = await get_client_screen(itgs, slug=screen.screen.slug)
                if screen_meta is None:
                    break
                subschema, _ = helper.deep_extract_value_and_subschema(
                    screen_meta.raw_schema, screen.screen.fixed, path
                )
                if (
                    subschema.get("type") != "string"
                    or subschema.get("format") != "flow_slug"
                ):
                    continue
                found_candidate = True
                description = subschema.get("description", "")
                if description == "The client flow to trigger" and path[-1] == ["flow"]:
                    # assuming shared_screen_configurable_trigger_001
                    parent_subschema, _ = helper.deep_extract_value_and_subschema(
                        screen_meta.raw_schema, screen.screen.fixed, path[:-1]
                    )
                    description = parent_subschema.get("description", "")
                yield allowed_slug_bytes, FlowPath(
                    type="path",
                    nodes=[
                        FlowPathNode(
                            type="edge",
                            via=FlowPathNodeEdgeViaScreenTrigger(
                                type="screen-trigger",
                                index=screen_index,
                                slug=screen.screen.slug,
                                name=screen.name,
                                trigger=path,
                                description=description,
                            ),
                            slug=allowed_slug,
                        )
                    ],
                )

            if not found_candidate:
                yield allowed_slug_bytes, FlowPath(
                    type="path",
                    nodes=[
                        FlowPathNode(
                            type="edge",
                            via=FlowPathNodeEdgeViaScreenAllowed(
                                type="screen-allowed",
                                index=screen_index,
                                slug=screen.screen.slug,
                                name=screen.name,
                            ),
                            slug=allowed_slug,
                        )
                    ],
                )

            yield allowed_slug_bytes, FlowDone(type="done")


def _deep_search_value(obj, value) -> Iterator[List[Union[str, int]]]:
    if obj == value:
        yield []
        return

    if isinstance(obj, dict):
        for key, sub_obj in obj.items():
            for path in _deep_search_value(sub_obj, value):
                yield [key] + path
        return

    if isinstance(obj, list):
        for idx, sub_obj in enumerate(obj):
            for path in _deep_search_value(sub_obj, value):
                yield [idx] + path


class ClientFlowAnalysisLockChangedEvent(BaseModel):
    """An event that is emitted whenever a lock is changed"""

    readers: int = Field(description="The number of readers currently holding a lock")
    writer: bool = Field(
        description="Whether there is a writer currently holding a lock"
    )


ClientFlowAnalysisLockChangedListenerFilter = Literal[
    "reader-lockable", "writer-lockable", "any"
]


@dataclass
class ClientFlowAnalysisLockChangedListener:
    filter: ClientFlowAnalysisLockChangedListenerFilter
    """The filter to apply before this listener cares"""
    received: Optional[ClientFlowAnalysisLockChangedEvent]
    """The event that was emitted, None if not emitted yet"""
    event: asyncio.Event
    """The event that is set when the event is emitted"""


def _listener_filter_applies(
    filter: ClientFlowAnalysisLockChangedListenerFilter,
    event: ClientFlowAnalysisLockChangedEvent,
) -> bool:
    if filter == "reader-lockable":
        return not event.writer
    elif filter == "writer-lockable":
        return not event.writer and not event.readers
    elif filter == "any":
        return True
    else:
        raise ValueError(f"Unknown filter {filter}")


LOCK_CHANGED_LISTENERS: Dict[
    Tuple[bytes, int], List[ClientFlowAnalysisLockChangedListener]
] = {}
"""The list of lock change listeners, indexed by (graph id, version). After the corresponding
lock changes the key is removed from the dictionary. Callers MUST ensure that after
a timeout period, they correctly cleanup from the dictionary to avoid a leak if
the lock change event is never emitted.
"""


async def listen_for_lock_changed(
    itgs: Itgs,
    /,
    *,
    graph: ClientFlowAnalysisEnvironment,
    version: int,
    filter: ClientFlowAnalysisLockChangedListenerFilter,
    timeout: float,
) -> Optional[ClientFlowAnalysisLockChangedEvent]:
    """Returns after the timeout period or when the next lock change event is emitted
    for the given graph environment and global graph analysis version. This is helpful
    when trying to acquire locks pessimistically (such as when an optimistic attempt
    already failed).

    This fully supports cancellation. Raises asyncio.TimeoutError if the timeout is reached.

    Args:
        itgs (Itgs): the integrations to (re)use
        graph (ClientFlowAnalysisEnvironment): the environment to analyze
        version (int): the global graph analysis version
        filter ("reader-lockable", "writer-lockable", "any"): the filter to apply before this listener cares
        timeout (int): the maximum time to wait in seconds
    """
    graph_id = graph.to_redis_identifier()

    listener = ClientFlowAnalysisLockChangedListener(
        filter=filter, received=None, event=asyncio.Event()
    )
    listener_task = asyncio.create_task(listener.event.wait())

    key = (graph_id, version)
    arr = LOCK_CHANGED_LISTENERS.get(key)
    if arr is None:
        arr = cast(List[ClientFlowAnalysisLockChangedListener], [])
        LOCK_CHANGED_LISTENERS[key] = arr
    arr.append(listener)

    try:
        await asyncio.wait_for(listener_task, timeout=timeout)
    finally:
        arr = LOCK_CHANGED_LISTENERS.get(key)
        if arr is None:
            return

        try:
            arr.remove(listener)
        except ValueError:
            ...

        if not arr:
            del LOCK_CHANGED_LISTENERS[key]


async def _listen_for_locks_changed():
    assert pps.instance is not None

    try:
        async with pps.PPSSubscription(
            pps.instance, "ps:client_flow_graph_analysis:lock_changed", "lcfa_lflc"
        ) as sub:
            async for message_raw in sub:
                message = io.BytesIO(message_raw)
                uid_length = int.from_bytes(message.read(4), "big")
                uid = message.read(uid_length)
                version = int.from_bytes(message.read(8), "big")

                if (uid, version) not in LOCK_CHANGED_LISTENERS:
                    continue

                readers = int.from_bytes(message.read(2), "big")
                writers = int.from_bytes(message.read(1), "big")

                assert writers in (1, 0), writers
                assert readers >= 0, readers

                event = ClientFlowAnalysisLockChangedEvent(
                    readers=readers, writer=bool(writers)
                )
                new_arr = []
                for listener in LOCK_CHANGED_LISTENERS.pop((uid, version)):
                    if not _listener_filter_applies(listener.filter, event):
                        new_arr.append(listener)
                        continue
                    listener.received = event
                    listener.event.set()
                if new_arr:
                    LOCK_CHANGED_LISTENERS[(uid, version)] = new_arr
    except Exception as e:
        if pps.instance.exit_event.is_set() and isinstance(e, pps.PPSShutdownException):
            return  # type: ignore
        await handle_error(e)
    finally:
        print("lib.client_flows.analysis#_listen_for_locks_changed exiting")


@lifespan_handler
async def listen_for_locks_changed():
    task = asyncio.create_task(_listen_for_locks_changed())
    yield
