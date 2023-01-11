"""Handles updating when the repository is updated"""
import subprocess
import platform
import perpetual_pub_sub as pps
import os


async def _listen_forever():
    """Subscribes to the redis channel updates:backend and upon
    recieving a message, calls /home/ec2-user/update_webapp.sh
    """
    print("updater subscribing")
    async with pps.PPSSubscription(pps.instance, "updates:backend", "updater") as sub:
        print("updater waiting for message")
        await sub.read()
        print("updater received message")

    print("updater triggering update_webapp.sh")
    if platform.platform().lower().startswith("linux"):
        print("using linux strategy")
        subprocess.Popen(
            "bash /home/ec2-user/update_webapp.sh > /dev/null 2>&1",
            shell=True,
            stdin=None,
            stdout=None,
            stderr=None,
            preexec_fn=os.setpgrp,
        )
    else:
        print("using windows strategy")
        subprocess.Popen(
            "bash /home/ec2-user/update_webapp.sh",
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )


async def listen_forever():
    """Subscribes to the redis channel updates:backend and upon
    recieving a message, calls /home/ec2-user/update_webapp.sh
    """
    if os.path.exists("updater.lock"):
        return
    with open("updater.lock", "w") as f:
        f.write(str(os.getpid()))

    try:
        await _listen_forever()
    finally:
        os.unlink("updater.lock")
        print("updater shutdown")
