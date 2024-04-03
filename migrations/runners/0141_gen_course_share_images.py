from itgs import Itgs


async def up(itgs: Itgs) -> None:
    jobs = await itgs.jobs()
    await jobs.enqueue("runners.ensure_course_share_images")
