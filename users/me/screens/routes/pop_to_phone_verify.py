import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from lib.client_flows.executor import (
    ClientScreenQueuePeekInfo,
    TrustedTrigger,
    execute_peek,
    execute_pop,
)
from typing import Annotated, Optional
from itgs import Itgs
import auth as std_auth
from phones.routes.start_verify import (
    START_VERIFY_RESPONSES_BY_CODE,
    StartVerifyRequest,
    StartVerifyResponse,
    start_verify,
)
from response_utils import response_to_bytes
import users.me.screens.auth

from users.me.screens.lib.realize_screens import realize_screens
from users.me.screens.models.peeked_screen import PeekScreenResponse
from visitors.lib.get_or_create_visitor import VisitorSource


router = APIRouter()


class PopToPhoneVerifyParametersTriggerRequest(BaseModel):
    slug: str = Field(description="The slug of the client flow to trigger")
    parameters: StartVerifyRequest = Field(description="The parameters to convert")


class PopToPhoneVerifyRequest(BaseModel):
    screen_jwt: str = Field(description="The JWT which lets you pop the screen")
    trigger: PopToPhoneVerifyParametersTriggerRequest = Field(
        description=(
            "The client flow to trigger with server parameters including the phone number and verification details"
        ),
    )


@router.post(
    "/pop_to_phone_verify",
    response_model=PeekScreenResponse,
    responses=START_VERIFY_RESPONSES_BY_CODE,
)
async def pop_screen_to_phone_verify(
    args: PopToPhoneVerifyRequest,
    platform: VisitorSource,
    visitor: Annotated[Optional[str], Header()] = None,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """A specialized pop endpoint which sends a code to the given phone number
    and then triggers a flow with server parameters set to like in the following
    example:

    ```json
    {
        "phone_number": "+15555555555",
        "verification": {
            "uid": "string",
            "expires_at": 1234567890
        }
    }
    ```

    Where the verification uid can be provided to /api/1/phones/verify/finish
    before the given expiration time in seconds since the unix epoch to add
    the phone to the users account.

    If the phone format is incorrect or we cannot send the code, this endpoint
    does nothing and returns an error.

    If the screen jwt provided is invalid or doesn't correspond to the current
    screen, the response will still have a successful status code and you will
    retrieve a valid peeked screen, though the request may have different side
    effects than expected (i.e., you might have put a forbidden page on the
    queue instead of the intended trigger). An error is returned if the provided
    authorization header for a user is invalid.

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
            return await _realize(
                await execute_peek(
                    itgs,
                    user_sub=std_auth_result.result.sub,
                    platform=platform,
                    trigger=TrustedTrigger(
                        flow_slug="error_bad_auth",
                        client_parameters={},
                        server_parameters={},
                    ),
                )
            )

        verify_response = await start_verify(args.trigger.parameters, authorization)

        if verify_response.status_code < 200 or verify_response.status_code >= 300:
            return verify_response

        raw_response = await response_to_bytes(verify_response)
        parsed_response = StartVerifyResponse.model_validate_json(raw_response)

        # this is just a estimate for the client to make the ui tell them to resend the code
        # rather than them putting in a stale one, so it being imperfect is fine
        expires_at = time.time() + 600

        return await _realize(
            await execute_pop(
                itgs,
                user_sub=std_auth_result.result.sub,
                platform=platform,
                expected_front_uid=screen_auth_result.result.user_client_screen_uid,
                trigger=(
                    TrustedTrigger(
                        flow_slug=args.trigger.slug,
                        client_parameters={},
                        server_parameters={
                            "phone_number": args.trigger.parameters.phone_number,
                            "verification": {
                                "uid": parsed_response.uid,
                                "expires_at": expires_at,
                            },
                        },
                    )
                ),
            )
        )
