from itgs import Itgs
from lib.emails.send import send_email
from lib.shared.job_callback import JobCallback
import time
import asyncio


async def up(itgs: Itgs) -> None:
    for email in ["tj@oseh.com", "paul@oseh.com"]:
        await send_email(
            itgs,
            email=email,
            subject="Just dropped: Oseh 3.0 – Bite-Sized, Personal, Impactful 🚀",
            template="emailOseh30Announcement",
            template_parameters=dict(),
            success_job=JobCallback(
                name="runners.emails.test_success_handler", kwargs={}
            ),
            failure_job=JobCallback(
                name="runners.emails.test_failure_handler", kwargs={}
            ),
            now=time.time(),
        )


if __name__ == "__main__":

    async def main():
        async with Itgs() as itgs:
            await up(itgs)

    asyncio.run(main())
