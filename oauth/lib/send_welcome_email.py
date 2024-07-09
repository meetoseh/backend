import os

from error_middleware import handle_warning
from itgs import Itgs
from lib.shared.job_callback import JobCallback
from lib.touch.links import abandon_link, create_buffered_link
from lib.touch.send import (
    encode_touch,
    initialize_touch,
    prepare_send_touch,
    send_touch_in_pipe,
)
from redis_helpers.run_with_prep import run_with_prep


async def send_welcome_email(itgs: Itgs, /, *, user_sub: str, name: str) -> None:
    """Sends the welcome email to the user with the given sub"""
    if os.environ["ENVIRONMENT"] != "dev":
        slack = await itgs.slack()
        await slack.send_oseh_bot_message(
            f"Sending welcome email to {user_sub} using name {name}"
        )

    success_callback_codes = []
    failure_callback_codes = []
    touch = initialize_touch(
        user_sub=user_sub,
        touch_point_event_slug="welcome",
        channel="email",
        event_parameters={"name": name},
        success_callback=JobCallback(
            name="runners.touch.persist_links",
            kwargs={"codes": success_callback_codes},
        ),
        failure_callback=JobCallback(
            name="runners.touch.abandon_links",
            kwargs={"codes": failure_callback_codes},
        ),
    )
    unsubscribe_link = await create_buffered_link(
        itgs,
        touch_uid=touch.uid,
        page_identifier="unsubscribe",
        page_extra={},
        preview_identifier="unsubscribe",
        preview_extra={"list": "marketing emails"},
        now=touch.queued_at,
        code_style="long",
    )
    root_frontend_url = os.environ["ROOT_FRONTEND_URL"]
    touch.event_parameters["unsubscribe_url"] = (
        f"{root_frontend_url}/l/{unsubscribe_link.code}"
    )
    success_callback_codes.append(unsubscribe_link.code)
    failure_callback_codes.append(unsubscribe_link.code)

    enc_touch = encode_touch(touch)
    redis = await itgs.redis()

    async def prep(force: bool):
        await prepare_send_touch(redis, force=force)

    async def func():
        return await send_touch_in_pipe(redis, touch, enc_touch)

    result = await run_with_prep(prep, func)
    if not result:
        await handle_warning(
            f"{__name__}:backpressure",
            f"canceling welcome send due to backpressure",
        )
        await abandon_link(itgs, code=unsubscribe_link.code)
        return
