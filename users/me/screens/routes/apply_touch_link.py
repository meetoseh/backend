from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from lib.client_flows.executor import (
    ClientScreenQueuePeekInfo,
    TrustedTrigger,
    execute_peek,
)
from lib.touch.links import click_link, create_click_uid
from models import STANDARD_ERRORS_BY_CODE
from typing import Annotated, Optional
from itgs import Itgs
import auth as std_auth
from notifications.routes.complete import (
    CompleteNotificationRequest,
    should_drop_touch_link_click,
    should_track_touch_link_click,
)

from users.me.screens.lib.realize_screens import realize_screens
from users.me.screens.models.peeked_screen import PeekScreenResponse
from visitors.lib.get_or_create_visitor import VisitorSource
from loguru import logger


router = APIRouter()


class ApplyTouchLinkRequest(BaseModel):
    code: str = Field(
        description="The touch link code to apply", min_length=1, max_length=255
    )
    click_uid: Optional[str] = Field(
        None,
        description="If a click on the link has already been tracked, the corresponding click uid",
    )


@router.post(
    "/apply_touch_link",
    response_model=PeekScreenResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def apply_touch_link(
    args: ApplyTouchLinkRequest,
    platform: VisitorSource,
    version: Optional[int] = None,
    visitor: Annotated[Optional[str], Header()] = None,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """A specialized peek endpoint intended for touch links (i.e., short links
    generally with the path `/l/<code>` or `/a/<code>`). Applies the destination of
    the touch link to the users screen queue and returns the front of their queue.

    Requires standard authorization for a user.
    """
    async with Itgs() as itgs:
        std_auth_result = await std_auth.auth_any(itgs, authorization)
        if std_auth_result.result is None:
            return std_auth_result.error_response

        user_sub = std_auth_result.result.sub

        async def _realize(screen: ClientScreenQueuePeekInfo):
            result = await realize_screens(
                itgs,
                user_sub=user_sub,
                platform=platform,
                visitor=visitor,
                result=screen,
            )

            return Response(
                content=result.__pydantic_serializer__.to_json(result),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=200,
            )

        if args.click_uid is None:
            if await should_drop_touch_link_click(
                itgs,
                CompleteNotificationRequest(code=args.code),
                std_auth_result,
                visitor,
            ):
                screen = await execute_peek(
                    itgs,
                    user_sub=std_auth_result.result.sub,
                    platform=platform,
                    version=version,
                    trigger=None,
                )
                return await _realize(screen)

            should_track = await should_track_touch_link_click(
                itgs,
                CompleteNotificationRequest(code=args.code),
                std_auth_result,
                visitor,
            )
            click_uid = create_click_uid()
            link = await click_link(
                itgs,
                code=args.code,
                visitor_uid=visitor,
                user_sub=std_auth_result.result.sub,
                track_type="on_click",
                parent_uid=None,
                clicked_at=None,
                should_track=should_track,
                click_uid=click_uid,
                now=None,
            )
        else:
            link = await click_link(
                itgs,
                code=args.code,
                visitor_uid=visitor,
                user_sub=std_auth_result.result.sub,
                track_type="post_login",
                parent_uid=args.click_uid,
                clicked_at=None,
                should_track=True,
            )

        if link is None:
            logger.warning(
                f"Ignoring bad touch link code {args.code} from user {user_sub} (no link found)"
            )
            screen = await execute_peek(
                itgs,
                user_sub=std_auth_result.result.sub,
                platform=platform,
                version=version,
                trigger=None,
            )
            return await _realize(screen)

        trigger = f"touch_link_{link.page_identifier}"
        logger.info(
            f"{user_sub} clicked {args.code}, which points to {link.page_identifier} with extra {link.page_extra}. Using client flow {trigger}"
        )
        screen = await execute_peek(
            itgs,
            user_sub=std_auth_result.result.sub,
            platform=platform,
            version=version,
            trigger=TrustedTrigger(
                flow_slug=trigger,
                client_parameters={},
                server_parameters={"code": args.code, **link.page_extra},
            ),
        )
        return await _realize(screen)
