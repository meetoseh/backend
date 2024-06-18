from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Any, Dict, Optional
from auth import AuthResult, auth_any
from itgs import Itgs
from redis.asyncio.client import Redis as AsyncioRedisClient
import random
from lib.touch.links import click_link, create_click_uid


router = APIRouter()


class CompleteNotificationRequest(BaseModel):
    code: str = Field(
        description="The code sent to the user", min_length=1, max_length=255
    )


class CompleteNotificationResponse(BaseModel):
    page_identifier: str = Field(
        description="The identifier of the page the user should be sent to"
    )
    page_extra: Dict[str, Any] = Field(
        description="Additional state to hydrate the page, which depends on the page_identifier"
    )
    click_uid: str = Field(
        description="A UID which can be used with the post_login route to "
        "indicate which user clicked the link"
    )


@router.post(
    "/complete",
    response_model=CompleteNotificationResponse,
    responses={
        404: {"description": "The code is not valid"},
    },
)
async def complete_notification(
    args: CompleteNotificationRequest,
    visitor: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
):
    """Determines where the user should be directed given they came from
    a notification with the given code. If a visitor has been initialized
    for the client already, it should be provided. Further, if the user is
    already logged in on the client, the authorization header should be
    provided.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        should_drop = await should_drop_touch_link_click(
            itgs, args, auth_result, visitor
        )
        if should_drop:
            # We'll try to spoil their data without being too obvious
            if random.random() < 0.1:
                return Response(
                    content=CompleteNotificationResponse(
                        page_identifier="home",
                        page_extra=dict(),
                        click_uid=create_click_uid(),
                    ),
                    status_code=200,
                    headers={
                        "Content-Type": "application/json; charset=utf-8",
                    },
                )
            return Response(status_code=404)

        should_track = await should_track_touch_link_click(
            itgs, args, auth_result, visitor
        )
        click_uid = create_click_uid()
        link = await click_link(
            itgs,
            code=args.code,
            visitor_uid=visitor,
            user_sub=auth_result.result.sub if auth_result.result is not None else None,
            track_type="on_click",
            parent_uid=None,
            clicked_at=None,
            should_track=should_track,
            click_uid=click_uid,
            now=None,
        )

        if link is None:
            return Response(status_code=404)

        return Response(
            content=CompleteNotificationResponse(
                page_identifier=link.page_identifier,
                page_extra=link.page_extra,
                click_uid=click_uid,
            ).model_dump_json(),
            headers={
                "Content-Type": "application/json; charset=utf-8",
            },
            status_code=200,
        )


async def should_track_touch_link_click(
    itgs: Itgs,
    args: CompleteNotificationRequest,
    auth_result: AuthResult,
    visitor: Optional[str],
) -> bool:
    """Decides if we should track the given request"""
    redis = await itgs.redis()

    code_count = await _incr_expire(
        redis,
        f"touch_links:click_ratelimit:codes:{args.code}".encode("utf-8"),
        3,
    )
    return code_count == 1


async def should_drop_touch_link_click(
    itgs: Itgs,
    args: CompleteNotificationRequest,
    auth_result: AuthResult,
    visitor: Optional[str],
) -> bool:
    """Determines if we should return a spurious response since we think
    they are scanning the keyspace.
    """
    if auth_result.success:
        # We ought to be able to use a more targetted approach for blocking
        # authenticated key scanning if it happens
        return False

    redis = await itgs.redis()
    unauthenticated_count = await _incr_expire(
        redis, b"touch_links:click_ratelimit:unauthenticated", 5
    )

    if unauthenticated_count < 500:
        # Still within somewhat reasonable bounds. Can increase this if the
        # number of users increases dramatically
        return False

    warning_count = await _incr_expire(
        redis, b"touch_links:click_ratelimit:warning", 3600
    )
    if warning_count == 1:
        slack = await itgs.slack()
        await slack.send_ops_message(
            f"Touch links click tracking detected automated code scanning; {unauthenticated_count=} in the last 5 seconds. "
            "Counter measures have been initiated to poison the data they are collecting"
        )
    return True


async def _incr_expire(redis: AsyncioRedisClient, key: bytes, duration: int) -> int:
    """Increments the given key, ensuring it expires after at most the given duration
    in seconds, and returns the value of the key after the increment
    """
    async with redis.pipeline() as pipe:
        pipe.multi()
        await pipe.incr(key)
        await pipe.expire(key, duration, nx=True)
        result = await pipe.execute()
    return result[0]
