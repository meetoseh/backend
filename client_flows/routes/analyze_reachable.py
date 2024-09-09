import asyncio
import time
from typing import Annotated, Dict, List, Literal, Optional, Union
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, validator
from error_middleware import handle_error, handle_warning
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from auth import auth_admin
from itgs import Itgs

import lib.client_flows.analysis as analysis


class ClientFlowsSearchReadableRequest(BaseModel):
    settings: analysis.ClientFlowAnalysisEnvironment = Field(
        description=(
            "Used to evaluate flow predicates, for example, replacer rules. "
            "For example, a browser user will not see the request review "
            "screen and thus cannot reach flows triggered via that screen. "
            "Reuse the exact same settings whenever possible for consistent results - "
            "in particular, you should never fill timestamps with the current time in "
            "seconds, instead use e.g. a specific time of day (e.g. 7am) or the start of the current hour"
        )
    )
    source: str = Field(
        description=(
            "The slug of the flow to start the search from. When searching "
            "the inverted graph, this is the target within the normal graph"
        )
    )
    target: Optional[str] = Field(
        None,
        description=(
            "If you are only interested in a specific target, may be indicated "
            "here to reduce the size of the response and the complexity of processing it."
        ),
    )
    inverted: bool = Field(
        description=(
            "True to search the inverted graph (i.e., where all the directed edges are reversed). "
            "False to search the normal graph."
        )
    )
    max_steps: Optional[int] = Field(
        None,
        description=(
            "For performance or as an analysis tool, you can only consider paths "
            "up to a certain length. If not specified, the search will continue until "
            "all paths are exhausted."
        ),
        ge=1,
    )
    targets_cursor: Optional[str] = Field(
        None,
        description=(
            "An opaque value that can be used for iterating through the targets that match. "
            "Either None for the first page, or the value of next_targets_cursor from a previous page."
        ),
    )
    offset_paths: int = Field(
        0,
        description="Must be zero unless the target is specified. Skips the first N paths.",
        ge=0,
    )
    limit_paths: int = Field(
        10,
        description=(
            "The maximum number of paths returned. Fewer paths may be returned even if "
            "more are available, so this cannot be used to detect the last page (use next_offset)"
        ),
    )

    @validator("offset_paths")
    def validate_offset_paths(cls, offset_paths, values):
        if values.get("target") is None and offset_paths != 0:
            raise ValueError("offset_paths must be zero unless target is specified")
        return offset_paths


class ClientFlowsSearchReadableResultItem(BaseModel):
    source: str = Field(description="The slug of the source flow in the normal graph")
    target: str = Field(description="The slug of the target flow in the normal graph")
    paths: List[analysis.FlowPath] = Field(
        description="The paths from source to target (in the normal graph) on this page. May be empty"
    )
    offset: int = Field(description="The number of paths skipped before this page")
    next_offset: Optional[int] = Field(
        description="The value to use for offset_paths to get the next page of results, or None if there "
        "are definitely no more paths"
    )


class ClientFlowsSearchReadableResponse(BaseModel):
    items: Dict[str, ClientFlowsSearchReadableResultItem] = Field(
        description="The paths from source to target (in the indicated graph, normal or inverted)"
    )
    next_targets_cursor: Optional[str] = Field(
        description="The value to use for targets_cursor to get the next page of results"
    )


router = APIRouter()

SUCCESS_204_TYPES = Literal["no_paths"]
SUCCESS_NO_PATHS_RESPONSE = Response(status_code=204)

ERROR_429_TYPES = Literal["ratelimited"]
ERROR_RATELIMITED_RESPONSE = Response(
    status_code=429,
    headers={"Content-Type": "application/json; charset=utf-8"},
    content=StandardErrorResponse[ERROR_429_TYPES](
        type="ratelimited", message="We are shedding load. Try again in a few seconds."
    ).model_dump_json(),
)


@router.post(
    "/analyze_reachable",
    response_model=ClientFlowsSearchReadableResponse,
    responses={
        **STANDARD_ERRORS_BY_CODE,
        "204": {
            "description": "There are no paths between the source and target",
        },
        "429": {
            "model": StandardErrorResponse[ERROR_429_TYPES],
            "description": "We are shedding load. Try again in a few seconds.",
        },
    },
)
async def client_flows_analyze_reachable(
    args: ClientFlowsSearchReadableRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Analyzes which flows can be reached by a particular user state from a given source.
    This can analyze either the normal graph (ie., A can be reached from B) or the inverted
    graph produced by taking the normal graph and inverting the direction of the edges.

    The response will include paths that are in the correct direction for the normal graph,
    but they will be keyed by the source if inverted is False and the target if inverted is True.

    There are two common ways to use this:

    - Iterating over targets: don't set `target`, `offset_paths`, or `limit_paths`. On the first
      call don't set `targets_cursor`. On subsequent calls, use the `next_targets_cursor` from the
      previous response. You are done when `next_targets_cursor` is None.

    - Iterating over paths between a specific source and target: set `target` and `limit_paths`.
      Initially, keep `offset_paths` to 0. On subsequent calls, use the `next_offset` from the previous
      response. You are done when `next_offset` is None

    Assuming you are reusing the exact same settings most of the time, this endpoint is very fast
    due to intelligent caching, and you will not get 429s.

    This requires standard authentication with an admin account.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        if args.target is None:
            return await _handle_no_target(itgs, args)
        return await _handle_target(itgs, args)


async def _partially_blocking_acquire_lock(
    itgs: Itgs,
    /,
    *,
    graph: analysis.ClientFlowAnalysisEnvironment,
    lock_type: Literal["reader", "writer"],
    attempt: int = 0,
) -> Union[
    analysis.ClientFlowAnalysisAcquireLockSuccess,
    analysis.ClientFlowAnalysisAcquireLockNotFound,
]:
    acquire_fn = (
        analysis.try_acquire_read_lock
        if lock_type == "reader"
        else analysis.try_acquire_write_lock
    )
    result = await acquire_fn(itgs, graph=graph, now=time.time())
    if result.type != "already_locked":
        return result

    if attempt >= 3:
        raise asyncio.TimeoutError("failed to acquire lock after 3 attempts")

    redis = await itgs.redis()
    current_version_bytes = await redis.get(b"client_flow_graph_analysis:version")
    current_version = (
        int(current_version_bytes) if current_version_bytes is not None else 0
    )

    lock_changed_task = asyncio.create_task(
        analysis.listen_for_lock_changed(
            itgs,
            graph=graph,
            version=current_version,
            filter="reader-lockable" if lock_type == "reader" else "writer-lockable",
            timeout=1,
        )
    )
    result = await acquire_fn(itgs, graph=graph, now=time.time())
    if result.type != "already_locked":
        if not lock_changed_task.cancel():
            try:
                await lock_changed_task
            except Exception as e:
                await handle_error(e, extra_info="ignored (got the lock)")
        return result
    await lock_changed_task  # may raise asyncio.TimeoutError
    return await _partially_blocking_acquire_lock(
        itgs, graph=graph, lock_type=lock_type, attempt=attempt + 1
    )


async def _handle_no_target(itgs: Itgs, args: ClientFlowsSearchReadableRequest):
    # we will ignore paths offset and paths limit; we will use paths offset 0 and paths limit 1

    try:
        if args.targets_cursor is not None:
            int(args.targets_cursor)
    except ValueError:
        await handle_warning(
            f"{__name__}:bad_targets_cursor",
            "targets_cursor is not an integer as is currently required, ignoring request",
        )
        return ERROR_RATELIMITED_RESPONSE

    try:
        read_lock_result = await _partially_blocking_acquire_lock(
            itgs, graph=args.settings, lock_type="reader"
        )
    except asyncio.TimeoutError:
        return ERROR_RATELIMITED_RESPONSE

    if read_lock_result.type == "not_found":
        return await _handle_no_target_with_write_lock(itgs, args)

    try:
        read_result = await analysis.try_read_reachable_flows_page_from_cache(
            itgs,
            lock=read_lock_result.lock,
            source=args.source,
            max_steps=args.max_steps,
            cursor=0 if args.targets_cursor is None else int(args.targets_cursor),
            inverted=args.inverted,
            now=int(time.time()),
        )
        if read_result.type == "success":
            return _format_no_target_result(args, read_result)
        if read_result.type == "lock_lost":
            await handle_warning(
                f"{__name__}:read_lock_stolen",
                "read lock was stolen while reading, probably because we took too long. not dangerous if so",
            )
            return ERROR_RATELIMITED_RESPONSE
        assert read_result.type == "not_initialized", read_result
    finally:
        unlock_result = await analysis.try_release_lock(
            itgs, lock=read_lock_result.lock, now=int(time.time())
        )
        if unlock_result.type != "success":
            await handle_warning(
                f"{__name__}:read_lock_stolen",
                "read lock was stolen before release, probably because we took too long. not dangerous if so",
            )
            return ERROR_RATELIMITED_RESPONSE

    return await _handle_no_target_with_write_lock(itgs, args)


async def _handle_no_target_with_write_lock(
    itgs: Itgs, args: ClientFlowsSearchReadableRequest
) -> Response:
    try:
        write_lock_result = await _partially_blocking_acquire_lock(
            itgs, graph=args.settings, lock_type="writer"
        )
    except asyncio.TimeoutError:
        return ERROR_RATELIMITED_RESPONSE

    assert write_lock_result.type == "success", write_lock_result
    try:
        # always need to recheck read whenever there was a period of not having the
        # lock
        read_result = await analysis.try_read_reachable_flows_page_from_cache(
            itgs,
            lock=write_lock_result.lock,
            source=args.source,
            max_steps=args.max_steps,
            cursor=0 if args.targets_cursor is None else int(args.targets_cursor),
            inverted=args.inverted,
            now=int(time.time()),
        )
        if read_result.type == "success":
            return _format_no_target_result(args, read_result)
        if read_result.type == "lock_lost":
            await handle_warning(
                f"{__name__}:no_target_with_write_lock:recheck_read:lock_lost",
                "write lock was stolen during recheck read",
            )
            return ERROR_RATELIMITED_RESPONSE

        fill_result = await analysis.transfer_reachable_flows_from_db(
            itgs,
            lock=write_lock_result.lock,
            source=args.source,
            max_steps=args.max_steps,
            inverted=args.inverted,
        )
        if fill_result.type == "lock_lost":
            await handle_warning(
                f"{__name__}:no_target_with_write_lock:fill:lock_lost",
                "write lock was stolen while filling, probably because we took too long. not dangerous if so",
            )
            return ERROR_RATELIMITED_RESPONSE
        assert fill_result.type == "success", fill_result

        read_result = await analysis.try_read_reachable_flows_page_from_cache(
            itgs,
            lock=write_lock_result.lock,
            source=args.source,
            max_steps=args.max_steps,
            cursor=0 if args.targets_cursor is None else int(args.targets_cursor),
            inverted=args.inverted,
            now=int(time.time()),
        )
        if read_result.type != "success":
            await handle_warning(
                f"{__name__}:no_target_with_write_lock:read_after_fill:{read_result.type}",
                "failed to read after fill, probably not dangerous",
            )
            return ERROR_RATELIMITED_RESPONSE

        return _format_no_target_result(args, read_result)
    finally:
        write_lock_result = await analysis.try_release_lock(
            itgs, lock=write_lock_result.lock, now=int(time.time())
        )
        if write_lock_result.type != "success":
            await handle_warning(
                f"{__name__}:no_target_with_write_lock:release_failed:{write_lock_result.type}",
                "write lock was stolen before release, probably because we took too long. not dangerous if so",
            )
            return ERROR_RATELIMITED_RESPONSE


def _format_no_target_result(
    args: ClientFlowsSearchReadableRequest,
    read_result: analysis.ReachableFlowsResultSuccess,
) -> Response:
    items: Dict[str, ClientFlowsSearchReadableResultItem] = {}
    for natural_target, natural_peeked_paths in read_result.flows.items.items():
        if natural_peeked_paths.first.type == "done":
            items[natural_target] = ClientFlowsSearchReadableResultItem(
                source=natural_target if args.inverted else args.source,
                target=args.source if args.inverted else natural_target,
                paths=[],
                offset=0,
                next_offset=None,
            )
        else:
            items[natural_target] = ClientFlowsSearchReadableResultItem(
                source=natural_target if args.inverted else args.source,
                target=args.source if args.inverted else natural_target,
                paths=(
                    [natural_peeked_paths.first]
                    if not args.inverted
                    else [
                        analysis.FlowPath(
                            type="path",
                            nodes=list(reversed(natural_peeked_paths.first.nodes)),
                        )
                    ]
                ),
                offset=0,
                next_offset=1 if natural_peeked_paths.count > 1 else None,
            )

    return Response(
        content=ClientFlowsSearchReadableResponse.__pydantic_serializer__.to_json(
            ClientFlowsSearchReadableResponse(
                items=items,
                next_targets_cursor=(
                    None
                    if read_result.flows.cursor is None
                    else str(read_result.flows.cursor)
                ),
            )
        )
    )


async def _handle_target(itgs: Itgs, args: ClientFlowsSearchReadableRequest):
    assert args.target is not None, args

    try:
        read_lock_result = await _partially_blocking_acquire_lock(
            itgs, graph=args.settings, lock_type="reader"
        )
    except asyncio.TimeoutError:
        return ERROR_RATELIMITED_RESPONSE

    if read_lock_result.type == "not_found":
        return await _handle_target_with_write_lock(itgs, args)

    try:
        read_result = await analysis.read_paths_page_from_cache(
            itgs,
            lock=read_lock_result.lock,
            source=args.source,
            target=args.target,
            max_steps=args.max_steps,
            inverted=args.inverted,
            offset=args.offset_paths,
            limit=min(args.limit_paths, 10),
            now=int(time.time()),
        )
        if read_result.type == "success":
            return _format_target_result(args, read_result)
        if read_result.type == "no_paths":
            return SUCCESS_NO_PATHS_RESPONSE
        if read_result.type == "lock_lost":
            await handle_warning(
                f"{__name__}:read_lock_stolen",
                "read lock was stolen while reading, probably because we took too long. not dangerous if so",
            )
            return ERROR_RATELIMITED_RESPONSE
        assert read_result.type == "not_found", read_result
    finally:
        unlock_result = await analysis.try_release_lock(
            itgs, lock=read_lock_result.lock, now=int(time.time())
        )
        if unlock_result.type != "success":
            await handle_warning(
                f"{__name__}:read_lock_stolen",
                "read lock was stolen before release, probably because we took too long. not dangerous if so",
            )
            return ERROR_RATELIMITED_RESPONSE

    return await _handle_target_with_write_lock(itgs, args)


async def _handle_target_with_write_lock(
    itgs: Itgs, args: ClientFlowsSearchReadableRequest
) -> Response:
    assert args.target is not None, args
    try:
        write_lock_result = await _partially_blocking_acquire_lock(
            itgs, graph=args.settings, lock_type="writer"
        )
    except asyncio.TimeoutError:
        return ERROR_RATELIMITED_RESPONSE

    assert write_lock_result.type == "success", write_lock_result
    try:
        # always need to recheck read whenever there was a period of not having the
        # lock
        read_result = await analysis.read_paths_page_from_cache(
            itgs,
            lock=write_lock_result.lock,
            source=args.source,
            target=args.target,
            max_steps=args.max_steps,
            inverted=args.inverted,
            offset=args.offset_paths,
            limit=min(args.limit_paths, 10),
            now=int(time.time()),
        )
        if read_result.type == "success":
            return _format_target_result(args, read_result)
        if read_result.type == "no_paths":
            return SUCCESS_NO_PATHS_RESPONSE
        if read_result.type == "lock_lost":
            await handle_warning(
                f"{__name__}:target_with_write_lock:lock_stolen",
                "write lock was stolen during recheck read",
            )
            return ERROR_RATELIMITED_RESPONSE

        fill_result = await analysis.transfer_reachable_flows_from_db(
            itgs,
            lock=write_lock_result.lock,
            source=args.source,
            max_steps=args.max_steps,
            inverted=args.inverted,
        )
        if fill_result.type == "lock_lost":
            await handle_warning(
                f"{__name__}:target_with_write_lock:lock_stolen",
                "write lock was stolen while filling, probably because we took too long. not dangerous if so",
            )
            return ERROR_RATELIMITED_RESPONSE
        assert fill_result.type == "success", fill_result

        read_result = await analysis.read_paths_page_from_cache(
            itgs,
            lock=write_lock_result.lock,
            source=args.source,
            target=args.target,
            max_steps=args.max_steps,
            inverted=args.inverted,
            offset=args.offset_paths,
            limit=min(args.limit_paths, 10),
            now=int(time.time()),
        )
        if read_result.type == "no_paths":
            return SUCCESS_NO_PATHS_RESPONSE
        if read_result.type != "success":
            await handle_warning(
                f"{__name__}:target_with_write_lock:read_after_fill:{read_result.type}",
                "failed to read after fill, probably not dangerous",
            )
            return ERROR_RATELIMITED_RESPONSE

        return _format_target_result(args, read_result)
    finally:
        write_lock_result = await analysis.try_release_lock(
            itgs, lock=write_lock_result.lock, now=int(time.time())
        )
        if write_lock_result.type != "success":
            await handle_warning(
                f"{__name__}:target_with_write_lock:release_failed:{write_lock_result.type}",
                "write lock was stolen before release, probably because we took too long. not dangerous if so",
            )
            return ERROR_RATELIMITED_RESPONSE


def _format_target_result(
    args: ClientFlowsSearchReadableRequest,
    read_result: analysis.ReadPathsPageResultSuccess,
):
    assert args.target is not None
    paths: List[analysis.FlowPath] = []
    have_more = not not read_result.page
    for natural_flow_path_or_done in read_result.page:
        if natural_flow_path_or_done.type == "done":
            have_more = False
            continue

        paths.append(
            natural_flow_path_or_done
            if not args.inverted
            else analysis.FlowPath(
                type="path", nodes=list(reversed(natural_flow_path_or_done.nodes))
            )
        )

    return Response(
        content=ClientFlowsSearchReadableResponse.__pydantic_serializer__.to_json(
            ClientFlowsSearchReadableResponse(
                items={
                    args.target: ClientFlowsSearchReadableResultItem(
                        source=args.source if not args.inverted else args.target,
                        target=args.target if not args.inverted else args.source,
                        paths=paths,
                        offset=args.offset_paths,
                        next_offset=(
                            None if not have_more else args.offset_paths + len(paths)
                        ),
                    )
                },
                next_targets_cursor=None,
            )
        )
    )
