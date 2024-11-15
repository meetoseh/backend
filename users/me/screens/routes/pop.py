import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from interactive_prompts.events.routes.join import get_user_created_at
from lib.client_flows.executor import (
    UntrustedTrigger,
    TrustedTrigger,
    execute_peek,
    execute_pop,
)
from models import AUTHORIZATION_UNKNOWN_TOKEN, STANDARD_ERRORS_BY_CODE
from typing import Annotated, Any, Optional
from itgs import Itgs
import auth as std_auth
from users.lib.stats import on_user_is_active
import users.me.screens.auth

from users.me.screens.lib.realize_screens import realize_screens
from users.me.screens.models.peeked_screen import PeekScreenResponse
from visitors.lib.get_or_create_visitor import VisitorSource


router = APIRouter()


class PopScreenClientFlowTriggerRequest(BaseModel):
    slug: str = Field(description="The slug of the client flow to trigger")
    parameters: Any = Field(
        description=(
            "The parameters for the flow. These will be parsed to produce "
            "the flows schema; on failure the trigger may be ignored or transformed."
        )
    )


class PopScreenRequest(BaseModel):
    screen_jwt: str = Field(description="The JWT which lets you pop the screen")
    trigger: Optional[PopScreenClientFlowTriggerRequest] = Field(
        None,
        description=(
            "If the client wants to trigger a client flow after popping but "
            "before peeking, the client flow to trigger.\n\n"
            "This trigger may be ignored or transformed silently. The client "
            "will never receive direct feedback on if the trigger occurred at "
            "all or as specified. Even if its accepted, it may not be the only "
            "trigger that occurs."
        ),
    )


@router.post(
    "/pop", response_model=PeekScreenResponse, responses=STANDARD_ERRORS_BY_CODE
)
async def pop_screen(
    args: PopScreenRequest,
    platform: VisitorSource,
    version: Optional[int] = None,
    visitor: Annotated[Optional[str], Header()] = None,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Called to pop the current screen off the queue and trigger the given flow
    before peeking the next screen.

    If the screen jwt provided is invalid or doesn't correspond to the current
    screen, the response will still have a successful status code and you will
    retrieve a valid peeked screen, though the request may have different side
    effects than expected (i.e., you might have put a forbidden page on the
    queue instead of the intended trigger). An error is only returned if the
    provided authorization header for a user is invalid.

    Requires standard authorization for a user.
    """
    if args.trigger is not None and args.trigger.parameters is None:
        args.trigger.parameters = {}

    async with Itgs() as itgs:
        std_auth_result = await std_auth.auth_any(itgs, authorization)
        if std_auth_result.result is None:
            return std_auth_result.error_response

        user_created_at = await get_user_created_at(
            itgs, sub=std_auth_result.result.sub
        )
        if user_created_at is None:
            return AUTHORIZATION_UNKNOWN_TOKEN
        await on_user_is_active(
            itgs,
            std_auth_result.result.sub,
            user_created_at=user_created_at,
            active_at=time.time(),
        )

        screen_auth_result = await users.me.screens.auth.auth_any(
            itgs, args.screen_jwt, prefix=None
        )
        if screen_auth_result.result is None:
            screen = await execute_peek(
                itgs,
                user_sub=std_auth_result.result.sub,
                platform=platform,
                version=version,
                trigger=TrustedTrigger(
                    flow_slug="error_bad_auth",
                    client_parameters={},
                    server_parameters={},
                ),
            )
        else:
            screen = await execute_pop(
                itgs,
                user_sub=std_auth_result.result.sub,
                platform=platform,
                version=version,
                expected_front_uid=screen_auth_result.result.user_client_screen_uid,
                trigger=(
                    None
                    if args.trigger is None
                    else UntrustedTrigger(
                        flow_slug=args.trigger.slug,
                        client_parameters=args.trigger.parameters,
                    )
                ),
            )

        result = await realize_screens(
            itgs,
            user_sub=std_auth_result.result.sub,
            platform=platform,
            visitor=visitor,
            result=screen,
        )

        return Response(
            content=result.__pydantic_serializer__.to_json(result),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=200,
        )
