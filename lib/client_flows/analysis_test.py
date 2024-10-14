"""Used this instead of unittest because unittest makes vscode go crazy and has a lot
of boilerplate for async setup
"""

import asyncio
from typing import Optional, cast
from itgs import Itgs
import perpetual_pub_sub
import lifespan
import lib.client_flows.analysis as analysis
import time


async def main():
    assert perpetual_pub_sub.instance is None
    perpetual_pub_sub.instance = perpetual_pub_sub.PerpetualPubSub()

    background_tasks = set()
    background_tasks.add(
        asyncio.create_task(perpetual_pub_sub.instance.run_in_background_async())
    )
    graph = analysis.ClientFlowAnalysisEnvironment(
        version=None,
        account_created_at=1704096000,
        now=1709280000,
        last_journey_rating=None,
        journeys_today=0,
        journal_entries_in_history_today=0,
        has_oseh_plus=False,
        platform="ios",
        has_recoverable_identity=False,
    )
    async with lifespan.top_level_lifespan_handler(None), Itgs() as itgs:
        print("Detecting and cleaning up any leaked keys...")
        redis = await itgs.redis()
        cursor = cast(Optional[int], None)
        while cursor != 0:
            result = await redis.scan(
                cursor if cursor is not None else 0,
                match=b"client_flow_graph_analysis:*",
            )
            cursor = int(result[0])

            for sub_key in result[1]:
                if sub_key == b"client_flow_graph_analysis:version":
                    continue
                sub_key_expire_time = await redis.expiretime(sub_key)  # type: ignore
                if int(sub_key_expire_time) <= 0:
                    print(f"  Detected leaked key: {sub_key}")
                    await redis.delete(sub_key)  # type: ignore
        print("Starting tests...\n\n")

        # Note the order matters a little bit; the write lock test will ensure
        # that we don't get not_found from the reader lock acquires. Beyond that,
        # order is irrelevant
        await _test_wrapper(
            "Write Lock (acquire + release)",
            test_write_lock_acquire_release,
            itgs,
            graph,
        )
        await _test_wrapper(
            "Write Lock (max one writer)",
            test_write_lock_max_one_writer,
            itgs,
            graph,
        )
        await _test_wrapper(
            "Read Lock (acquire + release)",
            test_read_lock_acquire_release,
            itgs,
            graph,
        )
        await _test_wrapper(
            "Read Lock (multiple readers)",
            test_read_lock_multiple_readers,
            itgs,
            graph,
        )
        await _test_wrapper(
            "Write Lock blocks Read Lock",
            test_write_and_read_lock_writer_blocks_reader,
            itgs,
            graph,
        )
        await _test_wrapper(
            "Read Lock blocks Write Lock",
            test_write_and_read_lock_reader_blocks_writer,
            itgs,
            graph,
        )
        await _test_wrapper(
            "Write Lock release can be detected",
            test_write_lock_release_publish,
            itgs,
            graph,
        )
        await _test_wrapper(
            "Read Lock release can be detected",
            test_read_lock_release_publish,
            itgs,
            graph,
        )
        await _test_wrapper(
            "Detecting lock changed does timeout",
            test_lockable_timeout,
            itgs,
            graph,
        )
        await _test_wrapper(
            "Find adjacent flows from empty",
            test_empty_adjacency_list,
            itgs,
            graph,
        )
        await _test_wrapper(
            "Find flows going to journal_chat",
            test_journal_chat_inverted_adjacent,
            itgs,
            graph,
        )
        await _test_wrapper(
            "Find what can be reached from empty in at most 2 steps",
            test_empty_in_two_steps,
            itgs,
            graph,
        )
        await _test_wrapper(
            "Find all the ways to get to the library",
            test_how_to_get_to_library,
            itgs,
            graph,
        )
        # must be after how_to_get_to_library
        await _test_wrapper(
            "Find paths from empty to library using inverted",
            test_paths_page_from_empty_to_library_using_inverted,
            itgs,
            graph,
        )
        await _test_wrapper(
            "Detect an uncomputed analysis (inverted to account)",
            test_can_detect_need_to_compute_inverted_to_account,
            itgs,
            graph,
        )
        await _test_wrapper(
            "Detect a computed analysis indicating no results (empty to error_flow_schema)",
            test_can_see_no_paths_empty_to_error_flow_schema,
            itgs,
            graph,
        )

    perpetual_pub_sub.instance.exit_event.set()
    await asyncio.wait(background_tasks, return_when=asyncio.ALL_COMPLETED)


async def _test_wrapper(name, func, *args, **kwargs):
    print(f"{name} -- Starting test")
    start_at = time.perf_counter()
    await func(*args, **kwargs)
    time_taken = time.perf_counter() - start_at
    print(f"{name} -- Test passed in {time_taken:.3f}s")


async def test_write_lock_acquire_release(
    itgs: Itgs, graph: analysis.ClientFlowAnalysisEnvironment
):
    lock_result = await analysis.try_acquire_write_lock(
        itgs, graph=graph, now=time.time()
    )
    assert lock_result.type == "success", lock_result
    unlock_result = await analysis.try_release_write_lock(
        itgs, lock=lock_result.lock, now=time.time()
    )
    assert unlock_result.type == "success", unlock_result


async def test_write_lock_max_one_writer(
    itgs: Itgs, graph: analysis.ClientFlowAnalysisEnvironment
):
    first_lock_result = await analysis.try_acquire_write_lock(
        itgs, graph=graph, now=time.time()
    )
    assert first_lock_result.type == "success", first_lock_result
    try:
        second_lock_result = await analysis.try_acquire_write_lock(
            itgs, graph=graph, now=time.time()
        )
        assert second_lock_result.type == "already_locked", second_lock_result
    finally:
        unlock_result = await analysis.try_release_write_lock(
            itgs, lock=first_lock_result.lock, now=time.time()
        )
        assert unlock_result.type == "success", unlock_result


async def test_read_lock_acquire_release(
    itgs: Itgs, graph: analysis.ClientFlowAnalysisEnvironment
):
    lock_result = await analysis.try_acquire_read_lock(
        itgs, graph=graph, now=time.time()
    )
    assert lock_result.type == "success", lock_result
    unlock_result = await analysis.try_release_read_lock(
        itgs, lock=lock_result.lock, now=time.time()
    )
    assert unlock_result.type == "success", unlock_result


async def test_read_lock_multiple_readers(
    itgs: Itgs, graph: analysis.ClientFlowAnalysisEnvironment
):
    lock_one_result = await analysis.try_acquire_read_lock(
        itgs, graph=graph, now=time.time()
    )
    assert lock_one_result.type == "success", lock_one_result
    try:
        lock_two_result = await analysis.try_acquire_read_lock(
            itgs, graph=graph, now=time.time()
        )
        assert lock_two_result.type == "success", lock_two_result
        unlock_two_result = await analysis.try_release_read_lock(
            itgs, lock=lock_two_result.lock, now=time.time()
        )
        assert unlock_two_result.type == "success", unlock_two_result
    finally:
        unlock_one_result = await analysis.try_release_read_lock(
            itgs, lock=lock_one_result.lock, now=time.time()
        )
        assert unlock_one_result.type == "success", unlock_one_result


async def test_write_and_read_lock_writer_blocks_reader(
    itgs: Itgs, graph: analysis.ClientFlowAnalysisEnvironment
):
    write_lock_result = await analysis.try_acquire_write_lock(
        itgs, graph=graph, now=time.time()
    )
    assert write_lock_result.type == "success", write_lock_result
    try:
        read_lock_result = await analysis.try_acquire_read_lock(
            itgs, graph=graph, now=time.time()
        )
        assert read_lock_result.type == "already_locked", read_lock_result
    finally:
        unlock_result = await analysis.try_release_write_lock(
            itgs, lock=write_lock_result.lock, now=time.time()
        )
        assert unlock_result.type == "success", unlock_result


async def test_write_and_read_lock_reader_blocks_writer(
    itgs: Itgs, graph: analysis.ClientFlowAnalysisEnvironment
):
    read_lock_result = await analysis.try_acquire_read_lock(
        itgs, graph=graph, now=time.time()
    )
    assert read_lock_result.type == "success", read_lock_result
    try:
        write_lock_result = await analysis.try_acquire_write_lock(
            itgs, graph=graph, now=time.time()
        )
        assert write_lock_result.type == "already_locked", write_lock_result
    finally:
        unlock_result = await analysis.try_release_read_lock(
            itgs, lock=read_lock_result.lock, now=time.time()
        )
        assert unlock_result.type == "success", unlock_result


async def test_write_lock_release_publish(
    itgs: Itgs, graph: analysis.ClientFlowAnalysisEnvironment
):
    write_lock_result = await analysis.try_acquire_write_lock(
        itgs, graph=graph, now=time.time()
    )
    assert write_lock_result.type == "success", write_lock_result
    try:
        lockable_task = asyncio.create_task(
            analysis.listen_for_lock_changed(
                itgs,
                graph=graph,
                version=write_lock_result.lock.version,
                filter="writer-lockable",
                timeout=1,
            )
        )
        await asyncio.sleep(0.1)
        assert lockable_task.done() is False, "waiting task finished too early"
        unlock_result = await analysis.try_release_write_lock(
            itgs, lock=write_lock_result.lock, now=time.time()
        )
        assert unlock_result.type == "success", unlock_result
        result = await lockable_task
        assert result is not None, "expected no timeout"
        assert result.writer == 0 and result.readers == 0, result
    except BaseException:
        await analysis.try_release_write_lock(
            itgs, lock=write_lock_result.lock, now=time.time()
        )


async def test_read_lock_release_publish(
    itgs: Itgs, graph: analysis.ClientFlowAnalysisEnvironment
):
    read_lock_result = await analysis.try_acquire_read_lock(
        itgs, graph=graph, now=time.time()
    )
    assert read_lock_result.type == "success", read_lock_result
    try:
        lockable_task = asyncio.create_task(
            analysis.listen_for_lock_changed(
                itgs,
                graph=graph,
                version=read_lock_result.lock.version,
                filter="writer-lockable",
                timeout=1,
            )
        )
        await asyncio.sleep(0.1)
        assert lockable_task.done() is False, "waiting task finished too early"
        unlock_result = await analysis.try_release_read_lock(
            itgs, lock=read_lock_result.lock, now=time.time()
        )
        assert unlock_result.type == "success", unlock_result
        result = await lockable_task
        assert result is not None, "expected no timeout"
        assert result.writer == 0 and result.readers == 0, result
    except BaseException:
        await analysis.try_release_read_lock(
            itgs, lock=read_lock_result.lock, now=time.time()
        )


async def test_lockable_timeout(
    itgs: Itgs, graph: analysis.ClientFlowAnalysisEnvironment
):
    try:
        result = await analysis.listen_for_lock_changed(
            itgs, graph=graph, version=0, filter="writer-lockable", timeout=0.1
        )
        assert result is None, "expected timeout"
    except asyncio.TimeoutError:
        pass


async def test_empty_adjacency_list(
    itgs: Itgs, graph: analysis.ClientFlowAnalysisEnvironment
):
    write_lock = await analysis.try_acquire_write_lock(
        itgs, graph=graph, now=time.time()
    )
    assert write_lock.type == "success", write_lock
    try:
        result = await analysis.transfer_reachable_flows_from_db(
            itgs, lock=write_lock.lock, source="empty", max_steps=1, inverted=False
        )
        assert result.type == "success", result

        cursor = cast(Optional[int], 0)
        while cursor is not None:
            result = await analysis.try_read_reachable_flows_page_from_cache(
                itgs,
                lock=write_lock.lock,
                source="empty",
                cursor=cursor,
                max_steps=1,
                inverted=False,
                now=int(time.time()),
            )
            assert result.type == "success", result
            cursor = result.flows.cursor
            for slug, item in result.flows.items.items():
                print(f"  found empty -> {slug} via exemplar {item.first!r}")
    finally:
        unlock_result = await analysis.try_release_write_lock(
            itgs, lock=write_lock.lock, now=time.time()
        )
        assert unlock_result.type == "success", unlock_result


async def test_journal_chat_inverted_adjacent(
    itgs: Itgs, graph: analysis.ClientFlowAnalysisEnvironment
):
    write_lock = await analysis.try_acquire_write_lock(
        itgs, graph=graph, now=time.time()
    )
    assert write_lock.type == "success", write_lock
    try:
        result = await analysis.transfer_reachable_flows_from_db(
            itgs,
            lock=write_lock.lock,
            source="journal_chat",
            max_steps=1,
            inverted=True,
        )
        assert result.type == "success", result

        cursor = cast(Optional[int], 0)
        while cursor is not None:
            result = await analysis.try_read_reachable_flows_page_from_cache(
                itgs,
                lock=write_lock.lock,
                source="journal_chat",
                cursor=cursor,
                max_steps=1,
                inverted=True,
                now=int(time.time()),
            )
            assert result.type == "success", result
            cursor = result.flows.cursor
            for slug, item in result.flows.items.items():
                print(
                    f"  found {slug} -> journal_chat via inverted exemplar {item.first!r}"
                )
    finally:
        unlock_result = await analysis.try_release_write_lock(
            itgs, lock=write_lock.lock, now=time.time()
        )
        assert unlock_result.type == "success", unlock_result


async def test_empty_in_two_steps(
    itgs: Itgs, graph: analysis.ClientFlowAnalysisEnvironment
):
    write_lock = await analysis.try_acquire_write_lock(
        itgs, graph=graph, now=time.time()
    )
    assert write_lock.type == "success", write_lock
    try:
        result = await analysis.transfer_reachable_flows_from_db(
            itgs, lock=write_lock.lock, source="empty", max_steps=2, inverted=False
        )
        assert result.type == "success", result

        cursor = cast(Optional[int], 0)
        while cursor is not None:
            result = await analysis.try_read_reachable_flows_page_from_cache(
                itgs,
                lock=write_lock.lock,
                source="empty",
                cursor=cursor,
                max_steps=2,
                inverted=False,
                now=int(time.time()),
            )
            assert result.type == "success", result
            cursor = result.flows.cursor
            for slug, item in result.flows.items.items():
                print(f"  found empty -> {slug} via exemplar {item.first!r}")
    finally:
        unlock_result = await analysis.try_release_write_lock(
            itgs, lock=write_lock.lock, now=time.time()
        )
        assert unlock_result.type == "success", unlock_result


async def test_how_to_get_to_library(
    itgs: Itgs, graph: analysis.ClientFlowAnalysisEnvironment
):
    write_lock = await analysis.try_acquire_write_lock(
        itgs, graph=graph, now=time.time()
    )
    assert write_lock.type == "success", write_lock
    try:
        result = await analysis.transfer_reachable_flows_from_db(
            itgs, lock=write_lock.lock, source="library", max_steps=None, inverted=True
        )
        assert result.type == "success", result

        cursor = cast(Optional[int], 0)
        while cursor is not None:
            result = await analysis.try_read_reachable_flows_page_from_cache(
                itgs,
                lock=write_lock.lock,
                source="library",
                cursor=cursor,
                max_steps=None,
                inverted=True,
                now=int(time.time()),
            )
            assert result.type == "success", result
            cursor = result.flows.cursor
            for slug, item in result.flows.items.items():
                print(f"  found {slug} -> library via inverted exemplar {item.first!r}")
    finally:
        unlock_result = await analysis.try_release_write_lock(
            itgs, lock=write_lock.lock, now=time.time()
        )
        assert unlock_result.type == "success", unlock_result


async def test_paths_page_from_empty_to_library_using_inverted(
    itgs: Itgs, graph: analysis.ClientFlowAnalysisEnvironment
):
    read_lock = await analysis.try_acquire_read_lock(itgs, graph=graph, now=time.time())
    assert read_lock.type == "success", read_lock
    try:
        result = await analysis.read_paths_page_from_cache(
            itgs,
            lock=read_lock.lock,
            source="library",
            target="empty",
            max_steps=None,
            inverted=True,
            offset=0,
            limit=10,
            now=int(time.time()),
        )
        assert result.type == "success", result

        for path in result.page:
            print(f"  found item {path}")
    finally:
        unlock_result = await analysis.try_release_read_lock(
            itgs, lock=read_lock.lock, now=time.time()
        )
        assert unlock_result.type == "success", unlock_result


async def test_can_detect_need_to_compute_inverted_to_account(
    itgs: Itgs, graph: analysis.ClientFlowAnalysisEnvironment
):
    read_lock = await analysis.try_acquire_read_lock(itgs, graph=graph, now=time.time())
    assert read_lock.type == "success", read_lock
    try:
        result = await analysis.try_read_reachable_flows_page_from_cache(
            itgs,
            lock=read_lock.lock,
            source="account",
            cursor=0,
            max_steps=None,
            inverted=True,
            now=int(time.time()),
        )
        assert result.type == "not_initialized", result

        result = await analysis.read_paths_page_from_cache(
            itgs,
            lock=read_lock.lock,
            source="account",
            target="empty",
            max_steps=None,
            inverted=True,
            offset=0,
            limit=1,
            now=int(time.time()),
        )
        assert result.type == "not_found", result
    finally:
        unlock_result = await analysis.try_release_read_lock(
            itgs, lock=read_lock.lock, now=time.time()
        )
        assert unlock_result.type == "success", unlock_result


async def test_can_see_no_paths_empty_to_error_flow_schema(
    itgs: Itgs, graph: analysis.ClientFlowAnalysisEnvironment
):
    write_lock = await analysis.try_acquire_write_lock(
        itgs, graph=graph, now=time.time()
    )
    assert write_lock.type == "success", write_lock
    try:
        print("  Transferring reachable from empty (unlimited steps)")
        started_at = time.perf_counter()
        result = await analysis.transfer_reachable_flows_from_db(
            itgs,
            lock=write_lock.lock,
            source="empty",
            max_steps=None,
            inverted=False,
        )
        print(
            f"  Done transfering reachable from empty (unlimited steps) in {time.perf_counter() - started_at:.3f}s"
        )
        assert result.type == "success", result
    finally:
        unlock_result = await analysis.try_release_write_lock(
            itgs, lock=write_lock.lock, now=time.time()
        )
        assert unlock_result.type == "success", unlock_result

    read_lock = await analysis.try_acquire_read_lock(itgs, graph=graph, now=time.time())
    assert read_lock.type == "success", read_lock
    try:
        result = await analysis.read_paths_page_from_cache(
            itgs,
            lock=read_lock.lock,
            source="empty",
            target="error_flow_schema",
            max_steps=None,
            inverted=False,
            offset=0,
            limit=1,
            now=int(time.time()),
        )
        assert result.type == "no_paths", result
    finally:
        unlock_result = await analysis.try_release_read_lock(
            itgs, lock=read_lock.lock, now=time.time()
        )
        assert unlock_result.type == "success", unlock_result


if __name__ == "__main__":
    asyncio.run(main())
