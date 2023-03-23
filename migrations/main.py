"""Handles coordinating which migrations to run. Migrations are run
in lexicographic order within the migrations/runner.py when the main()
function is called in this module. This is multi-process and multi-instance
safe - redis is used as a lock to prevent multiple processes from running
migrations at the same time.

It is strongly recommended that migrations be run in a separate process to
avoid slowing the boot time for the underlying web server.
"""
from itgs import Itgs
from typing import List, Set
from error_middleware import handle_error
import importlib
import os
import asyncio
import time
import socket
import db.utils


async def main():
    """Acquires a lock and runs any outstanding migrations which have not
    been run before.
    """
    hostname = socket.gethostname()
    try:
        async with Itgs() as itgs:
            redis = await itgs.redis()

            acquired_lock = await redis.setnx(
                "backend:migrations-lock", str(time.time())
            )
            if not acquired_lock:
                return

            try:
                conn = await itgs.conn()
                cursor = conn.cursor()
                await cursor.execute(
                    "CREATE TABLE IF NOT EXISTS migrations ("
                    "  id INTEGER PRIMARY KEY,"
                    "  name TEXT UNIQUE NOT NULL,"
                    "  run_at REAL NOT NULL"
                    ")"
                )

                slack = await itgs.slack()
                candidate_migrations_to_run: List[str] = []
                for path in os.scandir(os.path.join("migrations", "runners")):
                    if path.is_file() and path.name.endswith(".py"):
                        candidate_migrations_to_run.append(path.name)

                migrations_to_run = await determine_unrun_migrations(
                    itgs, candidate_migrations_to_run
                )
                migrations_to_run.sort()
                for migration in migrations_to_run:
                    mod_path = "migrations.runners." + migration[:-3]
                    print(f"{mod_path=}")
                    mod = importlib.import_module(mod_path)
                    await mod.up(itgs)
                    await cursor.execute(
                        "INSERT INTO migrations (name, run_at) VALUES (?, ?)",
                        (migration, time.time()),
                    )
                    await slack.send_ops_message(
                        f"ran migration `{migration}` on {hostname}"
                    )
                print("all done")
            except Exception as e:
                await handle_error(e)
            finally:
                await redis.delete("backend:migrations-lock")
    except Exception as e:
        await handle_error(e)
    finally:
        print("migrations shutdown")


async def determine_unrun_migrations(itgs: Itgs, migrations: List[str]) -> List[str]:
    max_per_query = 100

    migrations_to_run: Set[str] = set(migrations)

    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    for i in range(0, len(migrations), max_per_query):
        checking = migrations[i : i + max_per_query]
        response = await cursor.execute(
            f"SELECT name FROM migrations WHERE name IN ({db.utils.question_mark_list(len(checking))})",
            checking,
        )
        for row in response.results:
            migrations_to_run.remove(row[0])

    return list(migrations_to_run)


def main_sync():
    """Synchronous variant of main which starts an event loop and calls
    main() - must not be run in the context of an event loop
    """
    asyncio.run(main())


if __name__ == "__main__":
    from loguru import logger

    logger.add("backend.log", enqueue=True, rotation="100 MB")

    main_sync()
