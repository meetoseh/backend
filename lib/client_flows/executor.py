"""This module can produce the input to the client screen simulator and sync the
output back to the database. Also contains helpers for performing entire operations
(peek & pops)
"""

import json
import secrets
from typing import List, Literal, Optional, Tuple, Union, cast
from error_middleware import handle_warning
from itgs import Itgs
from lib.client_flows.client_flow_screen import ClientFlowScreen
from lib.client_flows.client_flow_source import ClientFlowSource
from lib.client_flows.client_screen_stats_preparer import ClientScreenStatsPreparer
from lib.client_flows.screen_cache import get_client_screen
from lib.client_flows.simulator import (
    ClientFlowSimulatorClientInfo,
    ClientFlowSimulatorScreen,
    ClientFlowSimulatorState,
    fetch_and_simulate_trigger,
    init_simulator_from_peek,
    init_simulator_from_pop,
    simulate_until_stable,
)
import io
import time
from dataclasses import dataclass
from loguru import logger

from visitors.lib.get_or_create_visitor import VisitorSource


@dataclass
class TryAndStoreSimulationResultSuccess:
    type: Literal["success"]


@dataclass
class TryAndStoreSimulationResultFailureWithQueue:
    type: Literal["failure_with_queue"]
    first: Optional[ClientFlowSimulatorScreen]
    second: Optional[ClientFlowSimulatorScreen]


@dataclass
class TryAndStoreSimulationResultFailureWithoutQueue:
    type: Literal["failure_without_queue"]


TryAndStoreSimulationResult = Union[
    TryAndStoreSimulationResultSuccess,
    TryAndStoreSimulationResultFailureWithQueue,
    TryAndStoreSimulationResultFailureWithoutQueue,
]


async def try_and_store_simulation_result(
    itgs: Itgs,
    /,
    *,
    client_info: ClientFlowSimulatorClientInfo,
    state: ClientFlowSimulatorState,
) -> TryAndStoreSimulationResult:
    """If the clients screen queue has not changed since the simulation was initialized,
    then this will update their queue to match the simulation results and return True.

    Otherwise, when the clients screen queue has been modified, this does nothing and returns
    False.

    Args:
        itgs (Itgs): the integrations to (re)use
        client_info (ClientFlowSimulatorClientInfo): the client info for the simulation
        state (ClientFlowSimulatorState): the state of the simulation
    """
    if not state.mutations:
        return TryAndStoreSimulationResultSuccess(type="success")

    executed_at = time.time()

    conn = await itgs.conn()
    cursor = conn.cursor("strong")

    scratch_uid = f"oseh_scr_{secrets.token_urlsafe(16)}"

    queries: List[Tuple[str, list]] = []

    if state.original is None:
        queries.append(
            (
                "INSERT INTO scratch(uid) "
                "SELECT ? "
                "WHERE"
                " NOT EXISTS ("
                "  SELECT 1 FROM users, user_client_screens"
                "  WHERE users.sub = ? AND users.id = user_client_screens.user_id "
                " )",
                [scratch_uid, client_info.user_sub],
            )
        )
    else:
        queries.append(
            (
                "INSERT INTO scratch(uid) "
                "SELECT ? "
                "WHERE"
                " ? = ("
                "  SELECT user_client_screens.uid FROM users, user_client_screens"
                "  WHERE users.sub = ? AND users.id = user_client_screens.user_id "
                "  ORDER BY user_client_screens.outer_counter DESC, user_client_screens.inner_counter ASC"
                "  LIMIT 1"
                " )",
                [
                    scratch_uid,
                    state.original.user_client_screen_uid,
                    client_info.user_sub,
                ],
            )
        )

    target_user_cte = (
        "WITH target_user(id) AS ("
        "SELECT users.id FROM users, scratch "
        "WHERE users.sub = ? AND scratch.uid = ?"
        ")"
    )
    target_user_cte_qargs = cast(list, [client_info.user_sub, scratch_uid])

    for mutation in state.mutations:
        if mutation.type == "empty_queue":
            queries.append(
                (
                    target_user_cte
                    + " DELETE FROM user_client_screens "
                    + "WHERE user_client_screens.user_id = (SELECT id FROM target_user)",
                    target_user_cte_qargs,
                )
            )
        elif mutation.type == "prepend":
            sql = io.StringIO()
            sql.write(target_user_cte)
            qargs = target_user_cte_qargs.copy()
            sql.write(
                ", batch("
                "uid,"
                "outer_counter,"
                "inner_counter,"
                "client_flow_uid,"
                "client_screen_uid,"
                "flow_client_parameters,"
                "flow_server_parameters,"
                "screen) AS (VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
            )
            for i, screen in enumerate(mutation.screens):
                if i != 0:
                    sql.write(", (?, ?, ?, ?, ?, ?, ?, ?)")
                qargs.extend(
                    [
                        screen.uid,
                        screen.outer_counter,
                        screen.inner_counter,
                        screen.client_flow_uid,
                        screen.client_screen_uid,
                        screen.flow_client_parameters,
                        screen.flow_server_parameters,
                        screen.screen,
                    ]
                )

            sql.write(
                ") INSERT INTO user_client_screens("
                " uid,"
                " user_id,"
                " outer_counter,"
                " inner_counter,"
                " client_flow_id,"
                " client_screen_id,"
                " flow_client_parameters,"
                " flow_server_parameters,"
                " screen,"
                " added_at "
                ") SELECT"
                " batch.uid,"
                " target_user.id,"
                " batch.outer_counter,"
                " batch.inner_counter,"
                " client_flows.id,"
                " client_screens.id,"
                " batch.flow_client_parameters,"
                " batch.flow_server_parameters,"
                " batch.screen,"
                " ? "
                "FROM batch, target_user, client_flows, client_screens "
                "WHERE"
                " client_flows.uid = batch.client_flow_uid"
                " AND client_screens.uid = batch.client_screen_uid"
            )
            qargs.append(executed_at)
            queries.append((sql.getvalue(), qargs))
        elif mutation.type == "skip":
            queries.append(
                (
                    target_user_cte + " DELETE FROM user_client_screens "
                    "WHERE user_client_screens.id = ("
                    "SELECT ucs.id FROM user_client_screens AS ucs "
                    "WHERE"
                    " ucs.user_id = (SELECT id FROM target_user) "
                    "ORDER BY ucs.outer_counter DESC, ucs.inner_counter ASC "
                    "LIMIT 1"
                    ")",
                    (target_user_cte_qargs),
                )
            )
        else:
            raise ValueError(f"Unknown mutation: {mutation}")

    queries.append(
        (
            "SELECT"
            " user_client_screens.uid,"
            " user_client_screens.outer_counter,"
            " user_client_screens.screen,"
            " user_client_screens.flow_client_parameters,"
            " user_client_screens.flow_server_parameters "
            "FROM users, user_client_screens "
            "WHERE"
            " users.sub = ?"
            " AND NOT EXISTS (SELECT 1 FROM scratch WHERE scratch.uid = ?)"
            " AND users.id = user_client_screens.user_id "
            "ORDER BY user_client_screens.outer_counter DESC, user_client_screens.inner_counter ASC "
            "LIMIT 2",
            [client_info.user_sub, scratch_uid],
        )
    )
    queries.append(
        (
            "DELETE FROM scratch WHERE uid = ?",
            [scratch_uid],
        )
    )

    response = await cursor.executemany3(queries)
    if response[0].rows_affected is not None and response[0].rows_affected > 0:
        return TryAndStoreSimulationResultSuccess(type="success")

    updated_front_response = response[-2]
    updated_front: List[ClientFlowSimulatorScreen] = []
    for row in updated_front_response.results or []:
        flow_screen = ClientFlowScreen.model_validate_json(row[2])
        screen = await get_client_screen(itgs, slug=flow_screen.screen.slug)
        if screen is None:
            await handle_warning(
                f"{__name__}:missing_screen",
                f"During pop for {client_info.user_sub}, failed to retrieve "
                f"queue due to unknown slug near front: {flow_screen.screen.slug}",
            )
            return TryAndStoreSimulationResultFailureWithoutQueue(
                type="failure_without_queue"
            )

        updated_front.append(
            ClientFlowSimulatorScreen(
                user_client_screen_uid=row[0],
                flow_screen=flow_screen,
                screen=screen,
                outer_counter=row[1],
                flow_client_parameters=json.loads(row[3]),
                flow_server_parameters=json.loads(row[4]),
            )
        )

    return TryAndStoreSimulationResultFailureWithQueue(
        type="failure_with_queue",
        first=None if not updated_front else updated_front[0],
        second=None if len(updated_front) < 2 else updated_front[1],
    )


@dataclass
class TryAndPreparePopResultSuccess:
    """We successfully initialized a simulator which already has the pop
    operation
    """

    type: Literal["success"]
    state: ClientFlowSimulatorState


@dataclass
class TryAndPreparePopResultUserNotFound:
    """The referenced user does not exist"""

    type: Literal["user_not_found"]


@dataclass
class TryAndPreparePopResultBadScreens:
    """There is a bad screen within the first 2 items of the queue, and
    `expecting_bad_screens` was False, so the query needs to be repeated
    with the more expensive variant `expecting_bad_screens=True`, which
    fetches the entire queue.
    """

    type: Literal["bad_screens"]


@dataclass
class TryAndPreparePopResultDesync:
    """We initialized a simulator, but expected_front_uid was not at the front. The
    initialized simulator has not done anything yet.
    """

    type: Literal["desync"]
    state: ClientFlowSimulatorState


TryAndPreparePopResult = Union[
    TryAndPreparePopResultSuccess,
    TryAndPreparePopResultUserNotFound,
    TryAndPreparePopResultBadScreens,
    TryAndPreparePopResultDesync,
]


async def try_and_prepare_pop(
    itgs: Itgs,
    /,
    *,
    client_info: ClientFlowSimulatorClientInfo,
    expected_front_uid: str,
    expecting_bad_screens: bool,
    read_consistency: Literal["none", "weak", "strong"],
) -> TryAndPreparePopResult:
    """Attempts to initialize a simulator for the given client, popping the front
    immediately in the simulation if `expected_front_uid` is at the front of the queue.

    Args:
        itgs (Itgs): the integrations to (re)use
        client_info (ClientFlowSimulatorClientInfo): the client info for the simulation
        expected_front_uid (str): if the `user_client_screens` row at the front of the queue
            has this uid, we pop it off in the simulation before returning. Otherwise, we
            return a fresh simulator without popping (via TryAndPreparePopResultDesync)
        expecting_bad_screens (bool): if True, we will fetch the entire queue to ensure
            we can handle some of the screens being missing. if False, we fetch only the first
            two items in the users queue, which means we might fail if one of them are missing
            (where missing means get_client_screen returns None for the corresponding slug,
            i.e., integrity error caused by adding a screen to a users queue then later deleting
            the screen)
        read_consistency ("none", "weak", "strong"): the read consistency to use
            for the query
    """
    conn = await itgs.conn()
    cursor = conn.cursor(read_consistency)

    response = await cursor.executeunified3(
        (
            (
                "SELECT 1 FROM users WHERE sub=?",
                [client_info.user_sub],
            ),
            (
                "SELECT "
                " user_client_screens.uid,"
                " user_client_screens.outer_counter,"
                " user_client_screens.screen,"
                " user_client_screens.flow_client_parameters,"
                " user_client_screens.flow_server_parameters "
                "FROM users, user_client_screens "
                "WHERE"
                " users.sub = ?"
                " AND users.id = user_client_screens.user_id "
                "ORDER BY user_client_screens.outer_counter DESC, user_client_screens.inner_counter ASC"
                + (" LIMIT 2" if not expecting_bad_screens else ""),
                [client_info.user_sub],
            ),
        )
    )

    if not response[0].results:
        return TryAndPreparePopResultUserNotFound(type="user_not_found")

    queue: List[ClientFlowSimulatorScreen] = []
    for row in response[1].results or []:
        flow_screen = ClientFlowScreen.model_validate_json(row[2])
        screen = await get_client_screen(itgs, slug=flow_screen.screen.slug)
        if screen is None:
            if expecting_bad_screens:
                continue

            await handle_warning(
                f"{__name__}:missing_screen",
                f"During failed execute for {client_info.user_sub}, failed to retrieve "
                f"queue due to unknown slug near front: {flow_screen.screen.slug}",
            )
            return TryAndPreparePopResultBadScreens(type="bad_screens")

        queue.append(
            ClientFlowSimulatorScreen(
                user_client_screen_uid=row[0],
                flow_screen=flow_screen,
                screen=screen,
                outer_counter=row[1],
                flow_client_parameters=json.loads(row[3]),
                flow_server_parameters=json.loads(row[4]),
            )
        )

    if not queue or queue[0].user_client_screen_uid != expected_front_uid:
        return TryAndPreparePopResultDesync(
            type="desync",
            state=init_simulator_from_peek(
                front=queue[0] if queue else None,
                queue=queue if expecting_bad_screens else None,
            ),
        )

    return TryAndPreparePopResultSuccess(
        type="success",
        state=init_simulator_from_pop(
            to_pop=queue[0],
            second=queue[1] if len(queue) > 1 else None,
            queue_after_pop=queue[1:] if expecting_bad_screens else None,
        ),
    )


@dataclass
class TryAndPreparePeekResultSuccess:
    """We successfully initialized a simulator"""

    type: Literal["success"]
    state: ClientFlowSimulatorState


@dataclass
class TryAndPreparePeekResultUserNotFound:
    """The referenced user does not exist"""

    type: Literal["user_not_found"]


@dataclass
class TryAndPreparePeekResultBadScreens:
    """There is a bad screen within the first item of the queue, and
    `expecting_bad_screens` was False, so the query needs to be repeated
    with the more expensive variant `expecting_bad_screens=True`, which
    fetches the entire queue.
    """

    type: Literal["bad_screens"]


TryAndPreparePeekResult = Union[
    TryAndPreparePeekResultSuccess,
    TryAndPreparePeekResultUserNotFound,
    TryAndPreparePeekResultBadScreens,
]


async def try_and_prepare_peek(
    itgs: Itgs,
    /,
    *,
    client_info: ClientFlowSimulatorClientInfo,
    expecting_bad_screens: bool,
    read_consistency: Literal["none", "weak", "strong"],
):
    """Attempts to initialize a simulator for the given client which starts
    off with the actual state of the clients screen queue.

    Args:
        itgs (Itgs): the integrations to (re)use
        client_info (ClientFlowSimulatorClientInfo): the client info for the simulation
        expecting_bad_screens (bool): if True, we will fetch the entire queue to ensure
            we can handle some of the screens being missing. if False, we fetch only the first
            item in the users queue, which means we might fail if it's missing
            (where missing means get_client_screen returns None for the
            corresponding slug, i.e., integrity error caused by adding a screen
            to a users queue then later deleting the screen)
        read_consistency ("none", "weak", "strong"): the read consistency to use
            for the query
    """

    conn = await itgs.conn()
    cursor = conn.cursor(read_consistency)

    response = await cursor.executeunified3(
        (
            (
                "SELECT 1 FROM users WHERE sub=?",
                [client_info.user_sub],
            ),
            (
                "SELECT "
                " user_client_screens.uid,"
                " user_client_screens.outer_counter,"
                " user_client_screens.screen,"
                " user_client_screens.flow_client_parameters,"
                " user_client_screens.flow_server_parameters "
                "FROM users, user_client_screens "
                "WHERE"
                " users.sub = ?"
                " AND users.id = user_client_screens.user_id "
                "ORDER BY user_client_screens.outer_counter DESC, user_client_screens.inner_counter ASC"
                + (" LIMIT 1" if not expecting_bad_screens else ""),
                [client_info.user_sub],
            ),
        )
    )

    if not response[0].results:
        return TryAndPreparePeekResultUserNotFound(type="user_not_found")

    queue: List[ClientFlowSimulatorScreen] = []
    for row in response[1].results or []:
        flow_screen = ClientFlowScreen.model_validate_json(row[2])
        screen = await get_client_screen(itgs, slug=flow_screen.screen.slug)
        if screen is None:
            if expecting_bad_screens:
                continue

            await handle_warning(
                f"{__name__}:missing_screen",
                f"During peek for {client_info.user_sub}, failed to retrieve "
                f"queue due to unknown slug near front: {flow_screen.screen.slug}",
            )
            return TryAndPreparePeekResultBadScreens(type="bad_screens")

        queue.append(
            ClientFlowSimulatorScreen(
                user_client_screen_uid=row[0],
                flow_screen=flow_screen,
                screen=screen,
                outer_counter=row[1],
                flow_client_parameters=json.loads(row[3]),
                flow_server_parameters=json.loads(row[4]),
            )
        )

    return TryAndPreparePeekResultSuccess(
        type="success",
        state=init_simulator_from_peek(
            front=queue[0] if queue else None,
            queue=queue if expecting_bad_screens else None,
        ),
    )


@dataclass
class GetPrefetchScreensResultSuccess:
    """We successfully found the screens we want the client to prefetch"""

    type: Literal["success"]
    prefetch: List[ClientFlowSimulatorScreen]


@dataclass
class GetPrefetchScreensResultUserNotFound:
    """The referenced user does not exist"""

    type: Literal["user_not_found"]


@dataclass
class GetPrefetchScreensResultDesync:
    """The screen we expected to be at the front no longer is"""

    type: Literal["desync"]


GetPrefetchScreensResult = Union[
    GetPrefetchScreensResultSuccess,
    GetPrefetchScreensResultUserNotFound,
    GetPrefetchScreensResultDesync,
]


def get_prefetch_screens_from_state(
    state: ClientFlowSimulatorState,
) -> Optional[GetPrefetchScreensResultSuccess]:
    """If we can determine the prefetch screens just using the simulator state,
    this will return them. Otherwise, this will return None.
    """
    if state.queue is not None:
        # since the state includes the entire queue, no need to hit the database
        front_outer_counter = state.queue[0].outer_counter
        result: List[ClientFlowSimulatorScreen] = []
        for idx, screen in enumerate(state.queue):
            if idx == 0:
                continue
            if screen.outer_counter != front_outer_counter:
                break
            result.append(screen)
        return GetPrefetchScreensResultSuccess(type="success", prefetch=result)

    for idx in range(len(state.mutations) - 1, -1, -1):
        mut = state.mutations[idx]
        if mut.type == "skip":
            # when initializing a pop in the happy path we don't initialize the
            # queue but it starts with a skip mutation so we need to hit the
            # db to get the screens to prefetch
            return None

        if mut.type == "empty_queue":
            raise NotImplementedError(
                "expected that if there were empty_queue, we'd have queue initialized"
            )

        if mut.type == "prepend":
            if not mut.screens:
                continue
            result: List[ClientFlowSimulatorScreen] = []
            for idx, screen in enumerate(mut.screens):
                if idx == 0:
                    continue
                result.append(
                    ClientFlowSimulatorScreen(
                        user_client_screen_uid=screen.uid,
                        flow_screen=screen.flow_screen_obj,
                        screen=screen.screen_obj,
                        outer_counter=screen.outer_counter,
                        flow_client_parameters=screen.flow_client_parameters_obj,
                        flow_server_parameters=screen.flow_server_parameters_obj,
                    )
                )
            return GetPrefetchScreensResultSuccess(type="success", prefetch=result)

        raise ValueError(f"Unknown mutation: {mut}")

    # If there were no mutations, then we can't determine the prefetch screens without
    # hitting the database
    return None


async def get_prefetch_screens(
    itgs: Itgs,
    /,
    *,
    client_info: ClientFlowSimulatorClientInfo,
    expected_front_uid: str,
    read_consistency: Literal["none", "weak", "strong"],
) -> GetPrefetchScreensResult:
    """Fetches which screens, if any, the client should start prefetching resources
    for if they are going to show the front screen which has the given uid.

    Args:
        itgs (Itgs): the integrations to (re)use
        client_info (ClientFlowSimulatorClientInfo): the client viewing the front
            of the queue
        expected_front_uid (str): the uid of the screen we expect to be at the front
        read_consistency ("none", "weak", "strong"): the read consistency to use
            for the query
    """
    conn = await itgs.conn()
    cursor = conn.cursor(read_consistency)

    response = await cursor.executeunified3(
        (
            (
                "SELECT 1 FROM users WHERE sub=?",
                [client_info.user_sub],
            ),
            (
                "SELECT"
                " ? = ("
                "SELECT ucs.uid FROM users AS u, user_client_screens AS ucs "
                "WHERE u.sub = ? AND u.id = ucs.user_id "
                "ORDER BY ucs.outer_counter DESC, ucs.inner_counter ASC "
                "LIMIT 1"
                ")",
                [expected_front_uid, client_info.user_sub],
            ),
            (
                "SELECT "
                " user_client_screens.uid,"
                " user_client_screens.outer_counter,"
                " user_client_screens.screen,"
                " user_client_screens.flow_client_parameters,"
                " user_client_screens.flow_server_parameters "
                "FROM users, user_client_screens "
                "WHERE"
                " users.sub = ?"
                " AND users.id = user_client_screens.user_id "
                " AND ? = ("  # we are careful to ensure this is not a correlated subquery
                "SELECT ucs.uid FROM users AS u, user_client_screens AS ucs "
                "WHERE u.sub = ? AND u.id = ucs.user_id "
                "ORDER BY ucs.outer_counter DESC, ucs.inner_counter ASC "
                "LIMIT 1"
                ")"
                " AND user_client_screens.outer_counter = ("  # we are careful to ensure this is not a correlated subquery
                "SELECT ucs.outer_counter FROM users AS u, user_client_screens AS ucs "
                "WHERE u.sub = ? AND u.id = ucs.user_id "
                "ORDER BY ucs.outer_counter DESC, ucs.inner_counter ASC "
                "LIMIT 1"
                " )"
                " AND user_client_screens.uid <> ? "
                "ORDER BY user_client_screens.outer_counter DESC, user_client_screens.inner_counter ASC",
                [
                    client_info.user_sub,
                    expected_front_uid,
                    client_info.user_sub,
                    client_info.user_sub,
                    expected_front_uid,
                ],
            ),
        )
    )

    if not response[0].results:
        return GetPrefetchScreensResultUserNotFound(type="user_not_found")

    if not response[1].results or not response[1].results[0][0]:
        return GetPrefetchScreensResultDesync(type="desync")

    prefetch: List[ClientFlowSimulatorScreen] = []
    for row in response[2].results or []:
        flow_screen = ClientFlowScreen.model_validate_json(row[2])
        screen = await get_client_screen(itgs, slug=flow_screen.screen.slug)
        if screen is None:
            continue

        prefetch.append(
            ClientFlowSimulatorScreen(
                user_client_screen_uid=row[0],
                flow_screen=flow_screen,
                screen=screen,
                outer_counter=row[1],
                flow_client_parameters=json.loads(row[3]),
                flow_server_parameters=json.loads(row[4]),
            )
        )

    return GetPrefetchScreensResultSuccess(type="success", prefetch=prefetch)


@dataclass
class ClientScreenQueuePeekInfo:
    """The information required for the client to display the front of their screen queue"""

    front: ClientFlowSimulatorScreen
    """The screen the client should display"""

    prefetch: List[ClientFlowSimulatorScreen]
    """May be empty; the screens we want the client to start prefetching resources for."""


@dataclass
class TrustedTrigger:
    flow_slug: str
    """The slug of the flow to trigger"""
    client_parameters: dict
    """The flow_client_parameters to use when triggering the flow"""
    server_parameters: dict
    """The flow_server_parameters to use when triggering the flow"""


async def execute_peek(
    itgs: Itgs,
    /,
    *,
    user_sub: str,
    platform: ClientFlowSource,
    trigger: Optional[TrustedTrigger],
) -> ClientScreenQueuePeekInfo:
    """Peeks the front of the queue, performs the given trusted trigger (if any),
    then performs any automatic triggers as a result of the front of the queue
    being peeked by the given platform, then returns the state that the client
    needs to display the front of their queue.
    """
    client_info = ClientFlowSimulatorClientInfo(user_sub=user_sub, platform=platform)
    expecting_bad_screens = False
    num_races = 0
    while True:
        if num_races > 5:
            raise Exception("Too many races")
        read_consistency = "none" if num_races == 0 else "weak"

        prepared_peek = await try_and_prepare_peek(
            itgs,
            client_info=client_info,
            expecting_bad_screens=expecting_bad_screens,
            read_consistency=read_consistency,
        )
        if prepared_peek.type == "user_not_found":
            raise ValueError(f"User not found: {user_sub}")

        if prepared_peek.type == "bad_screens":
            if expecting_bad_screens:
                raise ValueError(f"Bad screens for {user_sub} twice")
            expecting_bad_screens = True
            continue

        assert prepared_peek.type == "success"

        for _ in range(5):
            if trigger is not None:
                await fetch_and_simulate_trigger(
                    itgs,
                    client_info=client_info,
                    state=prepared_peek.state,
                    flow_slug=trigger.flow_slug,
                    flow_client_parameters=trigger.client_parameters,
                    flow_server_parameters=trigger.server_parameters,
                    source="server",
                    trusted=True,
                    is_pop_trigger=False,
                )
            await simulate_until_stable(
                itgs,
                client_info=client_info,
                state=prepared_peek.state,
            )
            store_result = await try_and_store_simulation_result(
                itgs,
                client_info=client_info,
                state=prepared_peek.state,
            )
            if store_result.type != "failure_with_queue":
                break

            num_races += 1
            read_consistency = "weak"
            prepared_peek = TryAndPreparePeekResultSuccess(
                type="success",
                state=init_simulator_from_peek(
                    front=store_result.first,
                ),
            )
        else:
            raise Exception("Too many races while simulating")

        if store_result.type == "failure_without_queue":
            num_races += 1
            continue

        assert store_result.type == "success"
        assert prepared_peek.state.current is not None

        ClientScreenStatsPreparer(prepared_peek.state.stats).incr_peeked(
            unix_date=prepared_peek.state.unix_date,
            platform=platform,
            slug=prepared_peek.state.current.screen.slug,
        )

        await prepared_peek.state.stats.store(itgs)
        trigger = None  # don't repeat trigger if prefetching fails

        prefetch = get_prefetch_screens_from_state(prepared_peek.state)
        if prefetch is None:
            prefetch = await get_prefetch_screens(
                itgs,
                client_info=client_info,
                expected_front_uid=prepared_peek.state.current.user_client_screen_uid,
                read_consistency=read_consistency,
            )

            if prefetch.type == "user_not_found":
                raise ValueError(f"User not found: {user_sub}")

            if prefetch.type == "desync":
                num_races += 1
                continue

            assert prefetch.type == "success"

        return ClientScreenQueuePeekInfo(
            front=prepared_peek.state.current,
            prefetch=prefetch.prefetch,
        )


@dataclass
class UntrustedTrigger:
    flow_slug: str
    """The slug of the flow to trigger"""

    client_parameters: dict
    """The flow_client_parameters to use when triggering the flow"""


async def execute_pop(
    itgs: Itgs,
    /,
    *,
    user_sub: str,
    platform: VisitorSource,
    expected_front_uid: str,
    trigger: Optional[Union[UntrustedTrigger, TrustedTrigger]],
) -> ClientScreenQueuePeekInfo:
    """Pops the front of the users queue, executes the given trigger, and then peeks
    the front of the queue.

    If the front of the users queue isn't what's expected, this instead executes
    `desync` and then peeks.

    Args:
        itgs (Itgs): the integrations to (re)use
        user_sub (str): the user to pop the front of their client screen queue
        platform (VisitorSource): the platform the user is viewing the client screen queue with
        expected_front_uid (str): the uid of the screen we expect to be at the front of the queue
        trigger (UntrustedTrigger, TrustedTrigger, None): the trigger to execute after popping.
            This trigger will only be executed if it's in the allowed list for the users current
            screen, it exists, its allowed to be triggered by the given platform, the parameters
            match, etc. Note that providing a trusted trigger allows specifying server parameters
            but does not otherwise change the behavior of the trigger.

    Returns:
        ClientScreenQueuePeekInfo: the information required for the client to display the front
            of their screen queue
    """
    client_info = ClientFlowSimulatorClientInfo(user_sub=user_sub, platform=platform)
    expecting_bad_screens = False
    num_races = 0
    while True:
        if num_races > 5:
            raise Exception("Too many races")
        read_consistency = "none" if num_races == 0 else "weak"

        prepared_pop = await try_and_prepare_pop(
            itgs,
            client_info=client_info,
            expected_front_uid=expected_front_uid,
            expecting_bad_screens=expecting_bad_screens,
            read_consistency=read_consistency,
        )

        if prepared_pop.type == "user_not_found":
            if num_races == 0:
                logger.warning(
                    f"First pop attempt for {user_sub} failed with user_not_found, retrying at weak consistency"
                )
                num_races += 1
                continue
            raise ValueError(f"User not found: {user_sub}, {num_races=}")

        if prepared_pop.type == "bad_screens":
            if expecting_bad_screens:
                raise ValueError(f"Bad screens for {user_sub} twice")
            logger.debug(f"Bad screens for {user_sub}, retrying with full queue")
            expecting_bad_screens = True
            continue

        assert prepared_pop.type in ("success", "desync"), prepared_pop

        for _ in range(5):
            logger.debug(
                f"Executing pop for {user_sub} on {platform} - {num_races=} gave {prepared_pop.type=}"
            )
            if prepared_pop.type == "desync":
                await fetch_and_simulate_trigger(
                    itgs,
                    client_info=client_info,
                    state=prepared_pop.state,
                    flow_slug="desync",
                    flow_client_parameters={},
                    flow_server_parameters={},
                    source="server",
                    trusted=True,
                    is_pop_trigger=False,
                )
            else:
                assert prepared_pop.state.original is not None
                ClientScreenStatsPreparer(prepared_pop.state.stats).incr_popped(
                    unix_date=prepared_pop.state.unix_date,
                    platform=platform,
                    slug=prepared_pop.state.original.screen.slug,
                )
                if trigger is not None:
                    if (
                        trigger.flow_slug != "skip"
                        and trigger.flow_slug
                        not in prepared_pop.state.original.flow_screen.allowed_triggers
                    ):
                        logger.warning(
                            f"{user_sub} attempted to trigger {trigger.flow_slug} on {platform} when popping "
                            f"the screen {prepared_pop.state.original.screen.slug}, but we only expected "
                            f"triggers: {prepared_pop.state.original.flow_screen.allowed_triggers}. Replacing "
                            "with forbidden."
                        )
                        await fetch_and_simulate_trigger(
                            itgs,
                            client_info=client_info,
                            state=prepared_pop.state,
                            flow_slug="forbidden",
                            flow_client_parameters={},
                            flow_server_parameters={},
                            source="server",
                            trusted=True,
                            is_pop_trigger=False,
                        )
                    else:
                        await fetch_and_simulate_trigger(
                            itgs,
                            client_info=client_info,
                            state=prepared_pop.state,
                            flow_slug=trigger.flow_slug,
                            flow_client_parameters=trigger.client_parameters,
                            flow_server_parameters=(
                                {}
                                if not isinstance(trigger, TrustedTrigger)
                                else trigger.server_parameters
                            ),
                            source=platform,
                            trusted=False,
                            is_pop_trigger=True,
                        )

            await simulate_until_stable(
                itgs,
                client_info=client_info,
                state=prepared_pop.state,
            )

            store_result = await try_and_store_simulation_result(
                itgs,
                client_info=client_info,
                state=prepared_pop.state,
            )
            logger.debug(
                f"Executing pop for {user_sub} on {platform} - {store_result.type=}"
            )

            if store_result.type != "failure_with_queue":
                break

            num_races += 1
            read_consistency = "weak"

            # It's possible we've turned a desync back into a success; in fact,
            # it's a very likely scenario:
            # - on screen A
            # - Pop the queue, screen A -> screen B
            # - Pop the queue again, providing screen B
            #   - Read is stale, gets screen A
            #   - Try desync
            #   - Store gives failure_with_queue, we now have screen B at the front

            if (
                store_result.first is not None
                and store_result.first.user_client_screen_uid == expected_front_uid
            ):
                logger.info(f"Pop for {user_sub=} is now in sync after failed store")
                # tmp to verify this occurs sometimes
                slack = await itgs.slack()
                await slack.send_web_error_message(
                    f"Converting {prepared_pop.type=} to success after store failure"
                )
                prepared_pop = TryAndPreparePopResultSuccess(
                    type="success",
                    state=init_simulator_from_pop(
                        to_pop=store_result.first,
                        second=store_result.second,
                        queue_after_pop=None,
                    ),
                )
            else:
                logger.info(f"Pop for {user_sub=} is desync after failed store")
                prepared_pop = TryAndPreparePopResultDesync(
                    type="desync",
                    state=init_simulator_from_peek(
                        front=store_result.first,
                    ),
                )
        else:
            raise Exception("Too many races while simulating")

        if store_result.type == "failure_without_queue":
            num_races += 1
            continue

        assert store_result.type == "success"
        assert prepared_pop.state.current is not None
        ClientScreenStatsPreparer(prepared_pop.state.stats).incr_peeked(
            unix_date=prepared_pop.state.unix_date,
            platform=platform,
            slug=prepared_pop.state.current.screen.slug,
        )
        await prepared_pop.state.stats.store(itgs)

        prefetch = get_prefetch_screens_from_state(prepared_pop.state)
        if prefetch is None:
            prefetch = await get_prefetch_screens(
                itgs,
                client_info=client_info,
                expected_front_uid=prepared_pop.state.current.user_client_screen_uid,
                read_consistency=read_consistency,
            )

            if prefetch.type == "user_not_found":
                raise ValueError(f"User not found: {user_sub}")

            if prefetch.type == "desync":
                return await execute_peek(
                    itgs, user_sub=user_sub, platform=platform, trigger=None
                )

            assert prefetch.type == "success"

        return ClientScreenQueuePeekInfo(
            front=prepared_pop.state.current,
            prefetch=prefetch.prefetch,
        )
