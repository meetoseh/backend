from contextlib import asynccontextmanager
import time
import asyncio


@asynccontextmanager
async def coarsen_time_with_sleeps(unit: float):
    """Sleeps to pad the time elapsed to the next unit of time. For example,
    if the unit is `1`, then pads the time to the next second (so if the
    yield actually takes 0.5s, this will sleep until 1s, for 1.2s, it will
    sleep until 2s, etc). This is a crude measure to weaken timing attacks
    when a constant-time implementation is not possible.
    """
    started_at = time.perf_counter()
    try:
        yield
    finally:
        elapsed_seconds = time.perf_counter() - started_at
        elapsed_in_t = int(elapsed_seconds / unit)
        sleep_for = (elapsed_in_t + 1) * unit - elapsed_seconds
        if sleep_for > 0:
            await asyncio.sleep(sleep_for)
