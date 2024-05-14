from dataclasses import dataclass
import json
import secrets
import time
from typing import List, Literal, Optional, Union, cast

import pytz

from error_middleware import handle_error
from itgs import Itgs
from lib.client_flows.client_flow_screen import ClientFlowScreen
from lib.client_flows.client_flow_source import ClientFlowSource
from lib.client_flows.client_flow_stats_preparer import ClientFlowStatsPreparer
from lib.client_flows.client_screen_stats_preparer import ClientScreenStatsPreparer
from lib.client_flows.flow_cache import ClientFlow, get_client_flow
from lib.client_flows.flow_flags import get_flow_flag_by_platform
from lib.client_flows.screen_cache import ClientScreen, get_client_screen
from lib.client_flows.screen_flags import get_screen_flag_by_platform
from lib.redis_stats_preparer import RedisStatsPreparer
import unix_dates

from loguru import logger


CHECKING_FLOW_SCHEMA_ON_TRUSTED = cast(bool, True)
"""If true, we will check to make sure the client and server parameters match the flows
schema, even when the input is trusted.

Minor performance hit, big debugging improvement.
"""


@dataclass
class ClientFlowSimulatorClientInfo:
    user_sub: str
    """The sub of the user who is requesting a screen"""

    platform: ClientFlowSource
    """Which platform the client is using, to speed up screen negotiation for
    screens which will definitely be unsupported
    """


@dataclass
class ClientFlowSimulatorScreen:
    user_client_screen_uid: str
    """The uid of the user_client_screen row which this simulator screen references"""

    flow_screen: ClientFlowScreen
    """The settings from the client flow whose trigger added this screen to the queue"""

    screen: ClientScreen
    """The underlying screen the flow screen references"""

    flow_client_parameters: dict
    """The client parameters used to trigger this screen"""

    flow_server_parameters: dict
    """The server parameters used to trigger this screen"""

    outer_counter: int
    """The value of `outer_counter` on the corresponding `user_client_screen` row, where
    higher values are earlier in the queue
    """


@dataclass
class ClientFlowSimulatorMutationEmptyQueue:
    """Completely empties out the queue"""

    type: Literal["empty_queue"]


@dataclass
class ClientFlowSimulatorUserClientScreen:
    """Describes a row which can be inserted into user_client_screens. Look there
    for docs
    """

    uid: str
    outer_counter: int
    inner_counter: int
    client_flow_uid: str

    client_screen_uid: str
    """Note: referencing this by uid improves referential integrity at a potentially
    significant performance cost, as it forces us to map from slugs to uids (and thus
    verify the slug actually exists)"""

    flow_client_parameters: str
    flow_server_parameters: str
    screen: str

    # Everything following this point is not used in the db insert, but just to avoid
    # needless serialization/deserialization cycles
    flow_obj: ClientFlow
    flow_screen_obj: ClientFlowScreen
    screen_obj: ClientScreen
    flow_client_parameters_obj: dict
    flow_server_parameters_obj: dict


@dataclass
class ClientFlowSimulatorMutationPrepend:
    """Prepends a list to the queue, such that the nth item in the list
    becomes the nth position of the queue
    """

    type: Literal["prepend"]
    screens: List[ClientFlowSimulatorUserClientScreen]


@dataclass
class ClientFlowSimulatorMutationSkip:
    """Skips the head of the queue"""

    type: Literal["skip"]


ClientFlowSimulatorMutation = Union[
    ClientFlowSimulatorMutationEmptyQueue,
    ClientFlowSimulatorMutationPrepend,
    ClientFlowSimulatorMutationSkip,
]


@dataclass
class ClientFlowSimulatorState:
    original: Optional[ClientFlowSimulatorScreen]
    """The screen at the front of the users screen queue when this simulator was initialized.
    In order for these mutations to be valid, the users screen queue must not have been mutated
    between fetching their state from the database and storing the result. By construction, it
    is sufficient to just verify that the front of the queue hasn't changed.
    """
    current: Optional[ClientFlowSimulatorScreen]
    """The simulated front of the users queue."""

    queue: Optional[List[ClientFlowSimulatorScreen]]
    """If we know the entire queue, such as because we are triggering a replace, the entire
    queue. None if we don't know the entire queue. Required for `skip` mutations.
    """

    mutations: List[ClientFlowSimulatorMutation]
    """The mutations need to occur to the users screen queue. This may be compacted
    arbitrarily (i.e., it is never necessary to do anything before a `empty_queue` mutation,
    since it will be undone).
    """

    stats: RedisStatsPreparer
    """The stats that need to be stored in redis if the simulated state is successfully
    applied to the user's screen queue. These track, for example, what client flows were
    triggered
    """

    created_at: float
    """The time this simulation is canonically occurring at for stats"""

    unix_date: int
    """The unix date for created at in the stats timezone"""


tz = pytz.timezone("America/Los_Angeles")


def init_simulator_from_peek(
    front: Optional[ClientFlowSimulatorScreen],
    *,
    queue: Optional[List[ClientFlowSimulatorScreen]] = None,
) -> ClientFlowSimulatorState:
    """Initializes a client flow simulator state as a result of peeking the front of the users
    queue. This may trigger flows if, for example, their queue is empty or the active
    screen isn't supported by their platform.
    """
    created_at = time.time()
    return ClientFlowSimulatorState(
        original=front,
        current=front,
        queue=queue if queue is not None else ([] if front is None else None),
        mutations=[],
        stats=RedisStatsPreparer(),
        created_at=created_at,
        unix_date=unix_dates.unix_timestamp_to_unix_date(created_at, tz=tz),
    )


def init_simulator_from_pop(
    to_pop: ClientFlowSimulatorScreen,
    second: Optional[ClientFlowSimulatorScreen],
    *,
    queue_after_pop: Optional[List[ClientFlowSimulatorScreen]] = None,
) -> ClientFlowSimulatorState:
    """Initializes a client flow simulator state as a result of preparing to pop the front of
    the queue.
    """
    created_at = time.time()
    return ClientFlowSimulatorState(
        original=to_pop,
        current=second,
        mutations=[
            ClientFlowSimulatorMutationSkip(type="skip"),
        ],
        queue=(
            queue_after_pop
            if queue_after_pop is not None
            else ([] if second is None else None)
        ),
        stats=RedisStatsPreparer(),
        created_at=created_at,
        unix_date=unix_dates.unix_timestamp_to_unix_date(created_at, tz=tz),
    )


def simulate_replace(
    state: ClientFlowSimulatorState,
) -> None:
    """Mutates the client flow simulator in-place to clear out the queue because we are
    triggering a flow which has `replace=True` set.

    Args:
        state (ClientFlowSimulatorState): The state to mutate
    """
    state.mutations = [ClientFlowSimulatorMutationEmptyQueue(type="empty_queue")]
    state.queue = []
    state.current = None


async def simulate_add_screens(
    itgs: Itgs,
    /,
    *,
    state: ClientFlowSimulatorState,
    source: ClientFlowSource,
    flow: ClientFlow,
    flow_client_parameters: dict,
    flow_server_parameters: dict,
) -> None:
    """Mutates the client flow simulator state in-place to prepend the given client flow's
    screens using the given parameters.
    """
    if not flow.screens:
        return

    outer_counter = state.current.outer_counter + 1 if state.current is not None else 1
    flow_client_parameters_serd = json.dumps(flow_client_parameters)
    flow_server_parameters_serd = json.dumps(flow_server_parameters)

    user_client_screens: List[ClientFlowSimulatorUserClientScreen] = []
    queue_prepend: Optional[List[ClientFlowSimulatorScreen]] = (
        [] if state.queue is not None else None
    )

    screen_stats = ClientScreenStatsPreparer(state.stats)
    for idx, flow_screen in enumerate(flow.screens):
        screen = await get_client_screen(itgs, slug=flow_screen.screen.slug)
        if screen is None:
            raise ValueError(
                f"Cannot trigger {flow.slug} ({flow.uid}): screen {flow_screen.screen.slug} not found"
            )

        screen_stats.incr_queued(
            unix_date=state.unix_date, platform=source, slug=screen.slug
        )

        user_client_screen_uid = f"oseh_ucs_{secrets.token_urlsafe(16)}"
        user_client_screens.append(
            ClientFlowSimulatorUserClientScreen(
                uid=user_client_screen_uid,
                outer_counter=outer_counter,
                inner_counter=idx,
                client_flow_uid=flow.uid,
                client_screen_uid=screen.uid,
                flow_client_parameters=flow_client_parameters_serd,
                flow_server_parameters=flow_server_parameters_serd,
                screen=flow_screen.model_dump_json(),
                flow_obj=flow,
                flow_screen_obj=flow_screen,
                screen_obj=screen,
                flow_client_parameters_obj=flow_client_parameters,
                flow_server_parameters_obj=flow_server_parameters,
            )
        )

        if idx != 0 and queue_prepend is None:
            continue

        simulator_screen = ClientFlowSimulatorScreen(
            user_client_screen_uid=user_client_screen_uid,
            flow_screen=flow_screen,
            screen=screen,
            outer_counter=outer_counter,
            flow_client_parameters=flow_client_parameters,
            flow_server_parameters=flow_server_parameters,
        )

        if idx == 0:
            state.current = simulator_screen

        if queue_prepend is not None:
            queue_prepend.append(simulator_screen)

    state.mutations.append(
        ClientFlowSimulatorMutationPrepend(
            type="prepend",
            screens=user_client_screens,
        )
    )

    if state.queue is not None and queue_prepend is not None:
        state.queue = queue_prepend + state.queue


async def materialize_queue(
    itgs: Itgs,
    /,
    *,
    state: ClientFlowSimulatorState,
    client_info: ClientFlowSimulatorClientInfo,
) -> None:
    """Fetches the entire user client screen queue for the given client fro mthe
    database and stores it in state.queue.
    """
    if state.queue is not None:
        return

    assert state.original is not None, "we knew the queue when we initialized the state"
    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    response = await cursor.execute(
        """
SELECT
    uid, screen, outer_counter, flow_client_parameters, flow_server_parameters
FROM users, user_client_screens
WHERE
    users.sub = ?
    AND user_client_screens.user_id = users.id
ORDER BY outer_counter DESC, inner_counter ASC
        """,
        (client_info.user_sub,),
    )

    fetched_queue: List[ClientFlowSimulatorScreen] = []
    if (
        response.results
        and response.results[0][0] == state.original.user_client_screen_uid
    ):
        for row in response.results:
            flow_screen = ClientFlowScreen.model_validate_json(row[1])
            screen = await get_client_screen(itgs, slug=flow_screen.screen.slug)
            if screen is None:
                logger.warning(
                    f"skip materializing queue is skipping {flow_screen.screen.slug} (screen missing)"
                )
                continue
            fetched_queue.append(
                ClientFlowSimulatorScreen(
                    user_client_screen_uid=row[0],
                    flow_screen=flow_screen,
                    screen=screen,
                    outer_counter=row[2],
                    flow_client_parameters=json.loads(row[3]),
                    flow_server_parameters=json.loads(row[4]),
                )
            )

    for mutation in state.mutations:
        if mutation.type == "empty_queue":
            fetched_queue = []
        elif mutation.type == "prepend":
            prepended: List[ClientFlowSimulatorScreen] = []
            for to_prepend in mutation.screens:
                prepended.append(
                    ClientFlowSimulatorScreen(
                        user_client_screen_uid=to_prepend.uid,
                        flow_screen=to_prepend.flow_screen_obj,
                        screen=to_prepend.screen_obj,
                        outer_counter=to_prepend.outer_counter,
                        flow_client_parameters=to_prepend.flow_client_parameters_obj,
                        flow_server_parameters=to_prepend.flow_server_parameters_obj,
                    )
                )
            fetched_queue = prepended + fetched_queue
        elif mutation.type == "skip":
            fetched_queue = fetched_queue[1:]
        else:
            raise ValueError(f"Unknown mutation: {mutation}")

    if not fetched_queue:
        assert state.current is None
    else:
        assert state.current is not None
        assert (
            state.current.user_client_screen_uid
            == fetched_queue[0].user_client_screen_uid
        )


async def simulate_skip(
    itgs: Itgs,
    /,
    *,
    state: ClientFlowSimulatorState,
    client_info: ClientFlowSimulatorClientInfo,
) -> None:
    """Mutates the client flow simulator state in-place to skip the front of the queue.
    This requires that the queue has been filled in on the state; if it hasn't, it will
    fetch the entire queue from the database (which could be expensive). If the queue has
    been changed in the database since the state was initialied, this will treat it like
    loading an empty queue (as it won't matter what we simulate since it won't be stored)
    """
    await materialize_queue(itgs, state=state, client_info=client_info)

    if not state.queue:
        raise ValueError("Cannot skip empty queue")

    state.mutations.append(ClientFlowSimulatorMutationSkip(type="skip"))
    state.current = state.queue[1] if len(state.queue) > 1 else None
    state.queue.pop(0)


async def simulate_trigger(
    itgs: Itgs,
    /,
    *,
    client_info: ClientFlowSimulatorClientInfo,
    state: ClientFlowSimulatorState,
    flow: ClientFlow,
    flow_client_parameters: dict,
    flow_server_parameters: dict,
    source: ClientFlowSource,
    trusted: bool,
    is_pop_trigger: bool,
):
    """Simulates the trigger of the given client flow, mutating the client flow simulator
    state and updating the stats accordingly.

    NOTE:
        This will swap to an  `error_screen_missing` trigger if a screen in the flow
        doesn't exist, though this functionality might be removed for performance reasons

    Args:
        itgs (Itgs): the integrations to (re)use
        client_info (ClientFlowSimulatorClientInfo): information about the client which
            is requesting a screen (for statistics)
        state (ClientFlowSimulatorState): the state of the client flow simulator, which
            this method will mutate
        flow (ClientFlow): the flow to trigger
        flow_client_parameters (dict): the client parameters to use
        flow_server_parameters (dict): the server parameters to use
        source (ClientFlowSource): the source of the trigger (for statistics)
        trusted (bool): for statistics only; true if the flow slug was selected by trusted
            server code, false if it was chosen from client input.
        is_pop_trigger (bool): for statistics only; true if we are performing triggers as the
            result of a pop, false if we are performing triggers as the result of a peek. If
            this is true, then when debugging issues it makes sense to look to the screen as
            a possible source of the problem.
    """

    original_mutations = state.mutations.copy()
    if flow.replaces:
        simulate_replace(state)

    try:
        await simulate_add_screens(
            itgs,
            state=state,
            flow=flow,
            flow_client_parameters=flow_client_parameters,
            flow_server_parameters=flow_server_parameters,
            source=source,
        )
        logger.info(f"Triggered {flow.slug}")
        ClientFlowStatsPreparer(state.stats).incr_triggered(
            unix_date=state.unix_date,
            platform=source,
            slug=flow.slug,
            trusted=trusted,
        )
    except ValueError as e:
        if flow.slug == "error_screen_missing":
            raise

        error_screen_missing = await get_client_flow(itgs, slug="error_screen_missing")
        if error_screen_missing is None:
            raise

        await handle_error(e)

        state.mutations = original_mutations
        logger.info(f"Replacing {flow.slug} with error_screen_missing")
        ClientFlowStatsPreparer(state.stats).incr_replaced(
            unix_date=state.unix_date,
            platform=source,
            screen_slug=_replaced_screen_slug(state, is_pop_trigger),
            original_flow_slug=flow.slug,
            replaced_flow_slug="error_screen_missing",
        )
        await simulate_trigger(
            itgs,
            client_info=client_info,
            state=state,
            flow=error_screen_missing,
            flow_client_parameters={},
            flow_server_parameters={},
            source="server",
            trusted=True,
            is_pop_trigger=False,
        )


async def fetch_and_simulate_trigger(
    itgs: Itgs,
    /,
    *,
    client_info: ClientFlowSimulatorClientInfo,
    state: ClientFlowSimulatorState,
    flow_slug: str,
    flow_client_parameters: dict,
    flow_server_parameters: dict,
    source: ClientFlowSource,
    trusted: bool,
    is_pop_trigger: bool,
) -> None:
    """Fetches the client flow with the given slug, then:

    If the flow does not exist, simulates `not_found`

    Otherwise, if the flow exists but cannot be triggered by the indicated source,
    simulates `wrong_platform`.

    Otherwise, if the flow exists and can be triggered by this platform but the flow
    parameters don't match its schema, simulates `error_flow_schema`. This check may
    be skipped for `trusted` inputs for performance.

    Finally, if the flow exists and the flow parameters match the schemas, simulates
    the requested flow
    """
    stats = ClientFlowStatsPreparer(state.stats)

    flow = await get_client_flow(itgs, slug=flow_slug)
    if flow is None:
        if flow_slug == "not_found":
            raise ValueError("Flow not found")

        logger.info(f"Replacing {flow_slug} with not_found")
        stats.incr_replaced(
            unix_date=state.unix_date,
            platform=source,
            screen_slug=_replaced_screen_slug(state, is_pop_trigger),
            original_flow_slug=flow_slug,
            replaced_flow_slug="not_found",
        )
        return await fetch_and_simulate_trigger(
            itgs,
            client_info=client_info,
            state=state,
            flow_slug="not_found",
            flow_client_parameters={},
            flow_server_parameters={},
            source="server",
            trusted=True,
            is_pop_trigger=is_pop_trigger,
        )

    if source != "server" and (flow.flags & get_flow_flag_by_platform(source)) == 0:
        logger.info(f"Replacing {flow_slug} with wrong_platform")
        stats.incr_replaced(
            unix_date=state.unix_date,
            platform=source,
            screen_slug=_replaced_screen_slug(state, is_pop_trigger),
            original_flow_slug=flow_slug,
            replaced_flow_slug="wrong_platform",
        )
        return await fetch_and_simulate_trigger(
            itgs,
            client_info=client_info,
            state=state,
            flow_slug="wrong_platform",
            flow_client_parameters={},
            flow_server_parameters={},
            source="server",
            trusted=True,
            is_pop_trigger=is_pop_trigger,
        )

    if not trusted or CHECKING_FLOW_SCHEMA_ON_TRUSTED:
        is_valid = True
        if not flow.client_schema.is_valid(flow_client_parameters):
            logger.info(
                f"Client parameters for {flow_slug} don't match schema:\n\n"
                f"client parameters:{flow_client_parameters}\n\n"
                "errors:\n- "
                + "\n- ".join(
                    str(e)
                    for e in flow.client_schema.iter_errors(flow_client_parameters)
                )
            )
            is_valid = False

        if not flow.server_schema.is_valid(flow_server_parameters):
            logger.info(
                f"Server parameters for {flow_slug} don't match schema:\n\n"
                f"server parameters:{flow_server_parameters}\n\n"
                "errors:\n- "
                + "\n- ".join(
                    str(e)
                    for e in flow.server_schema.iter_errors(flow_server_parameters)
                )
            )
            is_valid = False

        if not is_valid:
            if flow_slug == "error_flow_schema":
                raise ValueError("Flow schema error")

            logger.info(f"Replacing {flow_slug} with error_flow_schema")
            stats.incr_replaced(
                unix_date=state.unix_date,
                platform=source,
                screen_slug=_replaced_screen_slug(state, is_pop_trigger),
                original_flow_slug=flow_slug,
                replaced_flow_slug="error_flow_schema",
            )
            return await fetch_and_simulate_trigger(
                itgs,
                client_info=client_info,
                state=state,
                flow_slug="error_flow_schema",
                flow_client_parameters={},
                flow_server_parameters={},
                source="server",
                trusted=True,
                is_pop_trigger=is_pop_trigger,
            )

    await simulate_trigger(
        itgs,
        client_info=client_info,
        state=state,
        flow=flow,
        flow_client_parameters=flow_client_parameters,
        flow_server_parameters=flow_server_parameters,
        source=source,
        trusted=trusted,
        is_pop_trigger=is_pop_trigger,
    )


async def maybe_simulate_empty(
    itgs: Itgs,
    /,
    *,
    client_info: ClientFlowSimulatorClientInfo,
    state: ClientFlowSimulatorState,
) -> bool:
    """If the preconditions for the `empty` trigger are met, simulates the `empty` trigger
    and returns True. Otherwise, returns `none`

    Preconditions for the `empty` trigger: The front of the queue is empty
    """
    if state.current is not None:
        return False
    await fetch_and_simulate_trigger(
        itgs,
        client_info=client_info,
        state=state,
        flow_slug="empty",
        flow_client_parameters={},
        flow_server_parameters={},
        source="server",
        trusted=True,
        is_pop_trigger=False,
    )
    return True


async def maybe_simulate_skip(
    itgs: Itgs,
    /,
    *,
    client_info: ClientFlowSimulatorClientInfo,
    state: ClientFlowSimulatorState,
) -> bool:
    """If the preconditions for the `skip` trigger are met, pops the front of the queue,
    simulates the `skip` trigger and returns True. Otherwise, returns `none`

    Preconditions for the `skip` trigger: The front of the queue is not empty and that
    screen is not supported by the client.

    Note: this is the only way that the server pops the front of the queue. Conceptually,
    this is just a performance improvement over full round trips with the client and server.
    The biggest improvement is when many screens in a row will be unsupported, as this will
    also avoid tons of round trips with the database.
    """
    if state.current is None:
        return False

    if client_info.platform == "server":
        return False

    if (
        state.current.screen.flags & get_screen_flag_by_platform(client_info.platform)
    ) != 0:
        return False

    await simulate_skip(itgs, state=state, client_info=client_info)
    await fetch_and_simulate_trigger(
        itgs,
        client_info=client_info,
        state=state,
        flow_slug="skip",
        flow_client_parameters={},
        flow_server_parameters={},
        source="server",
        trusted=True,
        is_pop_trigger=False,
    )
    return True


async def simulate_until_stable(
    itgs: Itgs,
    /,
    *,
    client_info: ClientFlowSimulatorClientInfo,
    state: ClientFlowSimulatorState,
) -> None:
    """Keeps greedily triggering until no automatic trigger preconditions are satisfied."""
    while True:
        if await maybe_simulate_empty(itgs, client_info=client_info, state=state):
            continue
        if await maybe_simulate_skip(itgs, client_info=client_info, state=state):
            continue
        break


def _replaced_screen_slug(
    state: ClientFlowSimulatorState, is_pop_trigger: bool
) -> Optional[str]:
    return (
        state.original.screen.slug
        if state.original is not None and is_pop_trigger
        else None
    )
