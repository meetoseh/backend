import os
import socket
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from error_middleware import handle_error
from lib.client_flows.executor import (
    ClientScreenQueuePeekInfo,
    TrustedTrigger,
    execute_peek,
    try_and_prepare_peek,
)
from lib.client_flows.simulator import ClientFlowSimulatorClientInfo
from models import (
    AUTHORIZATION_UNKNOWN_TOKEN,
    STANDARD_ERRORS_BY_CODE,
    StandardErrorResponse,
)
from typing import Annotated, Optional
from itgs import Itgs
import auth as std_auth
import users.me.screens.auth

from oauth.routes.merge_confirm import (
    ERROR_409_TYPES,
    ERROR_503_TYPES,
    OauthMergeConfirmRequest,
)
from users.me.screens.lib.realize_screens import realize_screens
from users.me.screens.models.peeked_screen import PeekScreenResponse
from visitors.lib.get_or_create_visitor import VisitorSource

import oauth.lib.merging.confirm_merge_auth as confirm_merge_auth
from oauth.lib.merging.confirm_merge import attempt_confirm_merge
from loguru import logger


router = APIRouter()


class EmptyWithConfirmMergeTriggerRequest(BaseModel):
    slug: str = Field(
        description="The slug of the client flow to trigger with no parameters"
    )
    parameters: OauthMergeConfirmRequest = Field(
        description="The parameters to convert"
    )


class EmptyWithConfirmMergeRequest(BaseModel):
    screen_jwt: str = Field(description="The JWT which lets you pop the screen")
    trigger: EmptyWithConfirmMergeTriggerRequest = Field(
        description="The information which resolves the merge conflict",
    )


@router.post(
    "/empty_with_confirm_merge",
    response_model=PeekScreenResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def empty_with_confirm_merge(
    args: EmptyWithConfirmMergeRequest,
    platform: VisitorSource,
    version: Optional[int] = None,
    visitor: Annotated[Optional[str], Header()] = None,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """A specialized endpoint which is intended to be used after a merge
    conflict is detected. This will act like the merge confirmation
    endpoint /api/1/oauth/merge/confirm - and on success, will trigger
    the given flow.

    Merging accounts always clears the screen queue. So regardless of if a
    trigger is specified, or if the trigger corresponds to a flow which has
    `replaces=True`, this will act as if it triggered a flow with
    `replaces=True`. This is the primary reason why this endpoint is required,
    rather than the client just calling the merge confirmation endpoint
    directly, followed by popping the screen (which would instead result in a
    desync every time)

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

        screen_auth_result = await users.me.screens.auth.auth_any(
            itgs, args.screen_jwt, prefix=None
        )
        if screen_auth_result.result is None:
            return screen_auth_result.error_response

        confirm_merge_auth_result = await confirm_merge_auth.auth_presigned(
            itgs, args.trigger.parameters.merge_token, no_prefix=True
        )
        if confirm_merge_auth_result.result is None:
            return confirm_merge_auth_result.error_response

        if (
            std_auth_result.result.sub
            != confirm_merge_auth_result.result.original_user_sub
        ):
            return AUTHORIZATION_UNKNOWN_TOKEN

        if confirm_merge_auth_result.result.conflicts.email is not (
            args.trigger.parameters.email_hint is not None
        ):
            return Response(
                status_code=409,
                content=StandardErrorResponse[ERROR_409_TYPES](
                    type="conflict",
                    message=(
                        "The email hint was not provided when requested"
                        if args.trigger.parameters.email_hint is None
                        else "The email hint was provided when not requested"
                    ),
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        if confirm_merge_auth_result.result.conflicts.phone is not (
            args.trigger.parameters.phone_hint is not None
        ):
            return Response(
                status_code=409,
                content=StandardErrorResponse[ERROR_409_TYPES](
                    type="conflict",
                    message=(
                        "The phone hint was not provided when requested"
                        if args.trigger.parameters.phone_hint is None
                        else "The phone hint was provided when not requested"
                    ),
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        # prepare the peek and discard the result early, since we won't
        # be able to verify its unchanged later
        initial_prepared_peek = await try_and_prepare_peek(
            itgs,
            client_info=ClientFlowSimulatorClientInfo(
                platform=platform, version=version, user_sub=user_sub
            ),
            expecting_bad_screens=False,
            read_consistency="weak",
        )

        if initial_prepared_peek.type == "user_not_found":
            return AUTHORIZATION_UNKNOWN_TOKEN

        if (
            initial_prepared_peek.type != "success"
            or initial_prepared_peek.state.original is None
            or initial_prepared_peek.state.original.user_client_screen_uid
            != screen_auth_result.result.user_client_screen_uid
        ):
            logger.warning(
                f"empty_with_confirm_merge for {user_sub} - screen jwt is bad, peeking desync instead"
            )
            screen = await execute_peek(
                itgs,
                user_sub=user_sub,
                platform=platform,
                version=version,
                trigger=TrustedTrigger(
                    flow_slug="desync", client_parameters={}, server_parameters={}
                ),
            )
            return await _realize(screen)

        if (
            args.trigger.slug != "skip"
            and args.trigger.slug
            not in initial_prepared_peek.state.original.flow_screen.allowed_triggers
        ):
            logger.warning(
                f"empty_with_confirm_merge for {user_sub} - {args.trigger.slug} is not in allowed trigger list for this instance of {initial_prepared_peek.state.original.screen.slug}, peeking forbidden instead"
            )
            screen = await execute_peek(
                itgs,
                user_sub=user_sub,
                platform=platform,
                version=version,
                trigger=TrustedTrigger(
                    flow_slug="forbidden",
                    client_parameters={},
                    server_parameters={},
                ),
            )
            return await _realize(screen)

        try:
            result = await attempt_confirm_merge(
                itgs,
                original_user=std_auth_result.result,
                merge=confirm_merge_auth_result.result,
                email_hint=args.trigger.parameters.email_hint,
                phone_hint=args.trigger.parameters.phone_hint,
            )
        except Exception as e:
            await handle_error(
                e,
                extra_info=f"original user sub=`{std_auth_result.result.sub}`, merging user sub=`{confirm_merge_auth_result.result.merging_user_sub}`",
            )
            return Response(
                status_code=503,
                content=StandardErrorResponse[ERROR_503_TYPES](
                    type="service_unavailable",
                    message=(
                        "The email or phone hint may not have been one of the "
                        "available options, or the identity you are trying to "
                        "merge in has changed since you started the merge. "
                        "At best, you can try again from the beginning."
                    ),
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        if os.environ["ENVIRONMENT"] != "dev":
            try:
                slack = await itgs.slack()
                result_str = "success" if result else "failure"
                await slack.send_oseh_bot_message(
                    f"`{socket.gethostname()}` Original user `{std_auth_result.result.sub}` just performed "
                    f"the confirm account merge step to merge in the identity via provider "
                    f"{confirm_merge_auth_result.result.provider} and sub "
                    f"`{confirm_merge_auth_result.result.provider_sub}`."
                    f"\n\nResult: {result_str}",
                    preview=f"Confirm merge {result_str}",
                )
            except Exception as e:
                await handle_error(e)

        screen = await execute_peek(
            itgs,
            user_sub=user_sub,
            platform=platform,
            version=version,
            trigger=TrustedTrigger(
                flow_slug=args.trigger.slug, client_parameters={}, server_parameters={}
            ),
        )
        return await _realize(screen)
