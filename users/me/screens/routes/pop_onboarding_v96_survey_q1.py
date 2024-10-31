from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, StringConstraints
from annotated_types import Len
from lib.client_flows.executor import (
    ClientScreenQueuePeekInfo,
    TrustedTrigger,
    UntrustedTrigger,
    execute_peek,
    execute_pop,
)
from models import STANDARD_ERRORS_BY_CODE
from typing import Annotated, List, Optional
from itgs import Itgs
import auth as std_auth
import users.me.screens.auth
import users.lib.entitlements
from users.me.screens.lib.realize_screens import realize_screens
from users.me.screens.models.peeked_screen import PeekScreenResponse
from visitors.lib.get_or_create_visitor import VisitorSource


router = APIRouter()


class PopOnboardingV96SurveyQ1Parameters(BaseModel):
    choices: Annotated[
        List[Annotated[str, StringConstraints(max_length=63)]],
        Len(min_length=1, max_length=1),
    ] = Field(
        description="The emotion they want to feel",
    )


class PopOnboardingV96SurveyQ1ParametersTriggerRequest(BaseModel):
    slug: str = Field(description="The slug of the client flow to trigger")
    parameters: PopOnboardingV96SurveyQ1Parameters = Field(
        description="The parameters to convert"
    )


class PopOnboardingV96SurveyQ1Request(BaseModel):
    screen_jwt: str = Field(description="The JWT which lets you pop the screen")
    trigger: PopOnboardingV96SurveyQ1ParametersTriggerRequest = Field(
        description=(
            "The client flow to trigger with server parameters set with content, emotion, and goals"
        ),
    )


@router.post(
    "/pop_onboarding_v96_survey_q1",
    response_model=PeekScreenResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def pop_onboarding_v96_survey_q1(
    args: PopOnboardingV96SurveyQ1Request,
    platform: VisitorSource,
    version: Optional[int] = None,
    visitor: Annotated[Optional[str], Header()] = None,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """A specialized pop endpoint for app version v96 onboarding survey question 1,
    which extracts the actual choice (eliminating the number) and forwards it in the
    client parameters as "emotion"

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

        emotion = args.trigger.parameters.choices[0][4:]

        screen = await execute_pop(
            itgs,
            user_sub=std_auth_result.result.sub,
            platform=platform,
            version=version,
            expected_front_uid=screen_auth_result.result.user_client_screen_uid,
            trigger=UntrustedTrigger(
                flow_slug=args.trigger.slug,
                client_parameters={"emotion": emotion},
            ),
        )
        return await _realize(screen)
