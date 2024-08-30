import os
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from lib.client_flows.executor import (
    ClientScreenQueuePeekInfo,
    TrustedTrigger,
    UntrustedTrigger,
    execute_peek,
    execute_pop,
)
from lib.shared.describe_user import enqueue_send_described_user_slack_message
from models import STANDARD_ERRORS_BY_CODE
from typing import Annotated, Optional
from itgs import Itgs
import auth as std_auth
import users.me.screens.auth

from users.me.screens.lib.realize_screens import realize_screens
from users.me.screens.models.peeked_screen import PeekScreenResponse
from visitors.lib.get_or_create_visitor import VisitorSource


router = APIRouter()


class PopJoiningOptInGroupParameters(BaseModel):
    group_name: str = Field(description="The name of the group to join")
    forward_parameters: Optional[dict] = Field(
        None,
        description=(
            "The parameters to forward as the client parameters to the client flow"
        ),
    )


class PopJoiningOptInGroupTriggerRequest(BaseModel):
    slug: str = Field(description="The slug of the client flow to trigger")
    parameters: PopJoiningOptInGroupParameters = Field(
        description="The parameters to convert"
    )


class PopJoiningOptInGroupRequest(BaseModel):
    screen_jwt: str = Field(description="The JWT which lets you pop the screen")
    trigger: PopJoiningOptInGroupTriggerRequest = Field(
        description="The client flow to trigger",
    )


@router.post(
    "/pop_joining_opt_in_group",
    response_model=PeekScreenResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def pop_joining_opt_in_group(
    args: PopJoiningOptInGroupRequest,
    platform: VisitorSource,
    version: Optional[int] = None,
    visitor: Annotated[Optional[str], Header()] = None,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """A specialized pop endpoint which adds the user to the opt in group with the
    given name, if it exists, then functions like a normal pop endpoint using the
    forwarded client parameters.

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
            return await _realize(screen)

        conn = await itgs.conn()
        cursor = conn.cursor()
        response = await cursor.executeunified3(
            (
                (
                    "SELECT 1 FROM opt_in_groups WHERE name = ? COLLATE NOCASE",
                    (args.trigger.parameters.group_name,),
                ),
                (
                    """
INSERT INTO opt_in_group_users (
    user_id,
    opt_in_group_id
)
SELECT
    users.id,
    opt_in_groups.id
FROM users, opt_in_groups
WHERE
    users.sub = ?
    AND opt_in_groups.name = ? COLLATE NOCASE
    AND NOT EXISTS (
        SELECT 1 FROM opt_in_group_users AS oigu
        WHERE
            oigu.user_id = users.id
            AND oigu.opt_in_group_id = opt_in_groups.id
    )
                    """,
                    (user_sub, args.trigger.parameters.group_name),
                ),
            )
        )
        if not response[0].results:
            assert (
                response[1].rows_affected is None or response[1].rows_affected == 0
            ), response
            await enqueue_send_described_user_slack_message(
                itgs,
                message=f"{{name}} tried to join the opt in group `{args.trigger.parameters.group_name}`, but it does not exist",
                sub=std_auth_result.result.sub,
                channel="oseh_bot",
            )
        elif response[1].rows_affected is not None and response[1].rows_affected > 0:
            assert response[1].rows_affected == 1, response
            if os.environ["ENVIRONMENT"] != "dev":
                await enqueue_send_described_user_slack_message(
                    itgs,
                    message=f"{{name}} joined the opt in group `{args.trigger.parameters.group_name}`",
                    sub=std_auth_result.result.sub,
                    channel="oseh_bot",
                )

        screen = await execute_pop(
            itgs,
            user_sub=std_auth_result.result.sub,
            platform=platform,
            version=version,
            expected_front_uid=screen_auth_result.result.user_client_screen_uid,
            trigger=(
                UntrustedTrigger(
                    flow_slug=args.trigger.slug,
                    client_parameters=args.trigger.parameters.forward_parameters or {},
                )
            ),
        )
        return await _realize(screen)
