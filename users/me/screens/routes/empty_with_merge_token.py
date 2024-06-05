import os
import socket
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from error_middleware import handle_contextless_error
from lib.client_flows.executor import (
    ClientScreenQueuePeekInfo,
    TrustedTrigger,
    execute_peek,
)
from models import AUTHORIZATION_UNKNOWN_TOKEN, STANDARD_ERRORS_BY_CODE
from typing import Annotated, Optional
from itgs import Itgs
import auth as std_auth

from oauth.lib.merging.start_merge import attempt_start_merge
from users.me.screens.lib.realize_screens import realize_screens
from users.me.screens.models.peeked_screen import PeekScreenResponse
from visitors.lib.get_or_create_visitor import VisitorSource

import oauth.lib.merging.start_merge_auth as start_merge_auth


router = APIRouter()


class EmptyWithMergeTokenRequest(BaseModel):
    merge_token: str = Field(
        description="The merge token for the identity that is being merged in"
    )


@router.post(
    "/empty_with_merge_token",
    response_model=PeekScreenResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def empty_with_merge_token(
    args: EmptyWithMergeTokenRequest,
    platform: VisitorSource,
    visitor: Annotated[Optional[str], Header()] = None,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """A specialized endpoint which validates a merge token; if valid, the merge
    is started as if via `/api/1/oauth/merge/start` and the response is used to
    trigger:

    - `merge_no_change_required`: server parameters has `identities`, a list of
      `{"provider": str, "email": str}` options for how they can login
    - `merge_created_and_attached`: server parameters has `identities` for their
      old identities and `attached` for the new identity
    - `merge_trivial`: server parameters has `identities` for their old identities
      and `attached` for the list of new identities
    - `merge_confirmation_required`: server parameters has `original_identities`,
      `merging_identities`, and `conflict` which is `OauthMergeConfirmationRequiredDetails`

    All these flows (except possibly `merge_no_change_required`) can be assumed
    to have `replaces=True`, ie., they will empty the screen queue and provide
    new screens. For `merge_confirmation_required`, the merge has not completed
    yet until that screen is popped via `pop_with_confirm_merge`

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

        start_merge_auth_result = await start_merge_auth.auth_presigned(
            itgs, args.merge_token, no_prefix=True
        )
        if start_merge_auth_result.result is None:
            return start_merge_auth_result.error_response

        if (
            start_merge_auth_result.result.original_user_sub
            != std_auth_result.result.sub
        ):
            return AUTHORIZATION_UNKNOWN_TOKEN

        merge_result = await attempt_start_merge(
            itgs,
            original_user=std_auth_result.result,
            merge=start_merge_auth_result.result,
        )
        if os.environ["ENVIRONMENT"] != "dev":
            slack = await itgs.slack()
            await slack.send_oseh_bot_message(
                f"`{socket.gethostname()}` Original user `{std_auth_result.result.sub}` just performed "
                f"the first account merge step to merge in the identity via provider "
                f"{start_merge_auth_result.result.provider} and sub "
                f"`{start_merge_auth_result.result.provider_sub}`."
                f"\n\nResult: `{merge_result.result}`",
                preview=f"Start merge {merge_result.result}",
            )
        if merge_result.result == "no_change_required":
            screen = await execute_peek(
                itgs,
                user_sub=std_auth_result.result.sub,
                platform=platform,
                trigger=TrustedTrigger(
                    flow_slug="merge_no_change_required",
                    client_parameters={},
                    server_parameters={
                        "identities": [
                            v.model_dump() for v in merge_result.original_login_options
                        ]
                    },
                ),
            )
            return await _realize(screen)
        elif merge_result.result == "created_and_attached":
            assert len(merge_result.merging_login_options) == 1, merge_result
            screen = await execute_peek(
                itgs,
                user_sub=std_auth_result.result.sub,
                platform=platform,
                trigger=TrustedTrigger(
                    flow_slug="merge_created_and_attached",
                    client_parameters={},
                    server_parameters={
                        "identities": [
                            v.model_dump() for v in merge_result.original_login_options
                        ],
                        "attached": merge_result.merging_login_options[0].model_dump(),
                    },
                ),
            )
            return await _realize(screen)
        elif merge_result.result == "trivial_merge":
            screen = await execute_peek(
                itgs,
                user_sub=std_auth_result.result.sub,
                platform=platform,
                trigger=TrustedTrigger(
                    flow_slug="merge_trivial",
                    client_parameters={},
                    server_parameters={
                        "identities": [
                            v.model_dump() for v in merge_result.original_login_options
                        ],
                        "attached": [
                            v.model_dump() for v in merge_result.merging_login_options
                        ],
                    },
                ),
            )
            return await _realize(screen)
        elif merge_result.result == "confirmation_required":
            assert merge_result.conflict_details is not None, merge_result
            screen = await execute_peek(
                itgs,
                user_sub=std_auth_result.result.sub,
                platform=platform,
                trigger=TrustedTrigger(
                    flow_slug="merge_confirmation_required",
                    client_parameters={},
                    server_parameters={
                        "original_identities": [
                            v.model_dump() for v in merge_result.original_login_options
                        ],
                        "merging_identities": [
                            v.model_dump() for v in merge_result.merging_login_options
                        ],
                        "conflict": merge_result.conflict_details.model_dump(),
                    },
                ),
            )
            return await _realize(screen)
        else:
            await handle_contextless_error(
                extra_info=f"merge result type is unknown: `{merge_result.result}` for {user_sub} merging in {start_merge_auth_result.result.original_user_sub}"
            )
            return Response(status_code=500)
