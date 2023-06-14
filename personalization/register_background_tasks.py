from typing import Set
import asyncio


def register_background_tasks(container: Set[asyncio.Task]) -> None:
    """Starts and registers all background tasks required by the personalization module
    by storing them in the given container.
    """
