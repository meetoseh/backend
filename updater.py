"""Handles updating when the repository is updated"""

from itgs import Itgs
import perpetual_pub_sub as pps
from error_middleware import handle_error
import asyncio
import subprocess
import platform
import secrets
import socket
import os


async def _listen_forever():
    """Subscribes to the redis channel updates:backend and upon
    recieving a message, calls /home/ec2-user/update_webapp.sh
    """
    assert pps.instance is not None

    async with Itgs() as itgs:
        await release_update_lock_if_held(itgs)

        if os.environ.get("ENVIRONMENT") != "dev":
            slack = await itgs.slack()
            await slack.send_ops_message(f"backend {socket.gethostname()} ready")

    async with pps.PPSSubscription(pps.instance, "updates:backend", "updater") as sub:
        await sub.read()

    async with Itgs() as itgs:
        await acquire_update_lock(itgs)

    do_update()


async def acquire_update_lock(itgs: Itgs):
    our_identifier = secrets.token_urlsafe(16).encode("utf-8")
    local_cache = await itgs.local_cache()

    redis = await itgs.redis()
    while True:
        local_cache.set(b"updater-lock-key", our_identifier, expire=310)
        success = await redis.set(
            b"updates:backend:lock", our_identifier, nx=True, ex=300
        )
        if success:
            break
        await asyncio.sleep(1)


DELETE_IF_MATCH_SCRIPT = """
local key = KEYS[1]
local expected = ARGV[1]

local current = redis.call("GET", key)
if current == expected then
    redis.call("DEL", key)
    return 1
end
return 0
"""


async def release_update_lock_if_held(itgs: Itgs):
    local_cache = await itgs.local_cache()

    our_identifier = local_cache.get(b"updater-lock-key")
    if our_identifier is None:
        return

    redis = await itgs.redis()
    await redis.eval(DELETE_IF_MATCH_SCRIPT, 1, b"updates:backend:lock", our_identifier)  # type: ignore
    local_cache.delete(b"updater-lock-key")


def do_update():
    if platform.platform().lower().startswith("linux"):
        subprocess.Popen(
            "bash /home/ec2-user/update_webapp.sh > /dev/null 2>&1",
            shell=True,
            stdin=None,
            stdout=None,
            stderr=None,
            preexec_fn=os.setpgrp,  # type: ignore
        )
    else:
        subprocess.Popen(
            "bash /home/ec2-user/update_webapp.sh",
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )


async def listen_forever():
    """Subscribes to the redis channel updates:backend and upon
    recieving a message, calls /home/ec2-user/update_webapp.sh
    """
    assert pps.instance is not None

    if os.path.exists("updater.lock"):
        return
    with open("updater.lock", "w") as f:
        f.write(str(os.getpid()))

    try:
        await _listen_forever()
    except Exception as e:
        if pps.instance.exit_event.is_set() and isinstance(e, pps.PPSShutdownException):
            return
        await handle_error(e, extra_info="in backend updater")
    finally:
        os.unlink("updater.lock")
        print("updater shutdown")


def listen_forever_sync():
    """Subscribes to the redis channel updates:backend and upon
    recieving a message, calls /home/ec2-user/update_webapp.sh
    """
    asyncio.run(listen_forever())


if __name__ == "__main__":
    listen_forever_sync()
