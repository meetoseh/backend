import datetime
import json
import secrets
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, StringConstraints
from annotated_types import Len
import pytz
from error_middleware import handle_warning
from lib.client_flows.executor import (
    ClientScreenQueuePeekInfo,
    TrustedTrigger,
    UntrustedTrigger,
    execute_peek,
    execute_pop,
)
from lib.journals.master_keys import get_journal_master_key_for_encryption
from lib.shared.describe_user import enqueue_send_described_user_slack_message
from models import STANDARD_ERRORS_BY_CODE
from typing import Annotated, List, Optional
from itgs import Itgs
import auth as std_auth
from users.lib.timezones import get_user_timezone
import users.me.screens.auth
import users.lib.entitlements
from users.me.screens.lib.extract_choices import extract_choices
from users.me.screens.lib.realize_screens import realize_screens
from users.me.screens.models.peeked_screen import PeekScreenResponse
from visitors.lib.get_or_create_visitor import VisitorSource
import unix_dates


router = APIRouter()


class PopOnboardingV96SurveyQ3Parameters(BaseModel):
    emotion: Annotated[str, StringConstraints(max_length=63)] = Field(
        description="The emotion they want to feel more of"
    )
    goals: Annotated[
        List[Annotated[str, StringConstraints(max_length=255)]],
        Len(min_length=1, max_length=6),
    ] = Field(
        description="The goals they want to achieve",
    )
    checked: Annotated[
        List[Annotated[str, StringConstraints(max_length=255)]],
        Len(min_length=1, max_length=1),
    ] = Field(
        default_factory=lambda: ["[0] __appfix"],
        description="Their biggest challenge right now",
    )


class PopOnboardingV96SurveyQ3ParametersTriggerRequest(BaseModel):
    slug: str = Field(description="The slug of the client flow to trigger")
    parameters: PopOnboardingV96SurveyQ3Parameters = Field(
        description="The parameters to convert"
    )


class PopOnboardingV96SurveyQ3Request(BaseModel):
    screen_jwt: str = Field(description="The JWT which lets you pop the screen")
    trigger: PopOnboardingV96SurveyQ3ParametersTriggerRequest = Field(
        description=(
            "The client flow to trigger with server parameters set with content, emotion, goals, and challenge"
        ),
    )


@router.post(
    "/pop_onboarding_v96_survey_q3",
    response_model=PeekScreenResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def pop_onboarding_v96_survey_q3(
    args: PopOnboardingV96SurveyQ3Request,
    platform: VisitorSource,
    version: Optional[int] = None,
    visitor: Annotated[Optional[str], Header()] = None,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """A specialized pop endpoint for app version v96 onboarding survey question 2,
    which formats the current emotion and goals (as "choices") into the dynamic text
    content related to those goals as well as forwarding the emotion and goals for
    later storage.

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

        emotion = args.trigger.parameters.emotion
        goals = args.trigger.parameters.goals

        checked = await extract_choices(
            itgs,
            user_sub=user_sub,
            given=args.trigger.parameters.checked,
            default=["[0] Managing stress"],
        )

        challenge = checked[0][4:]

        master_key = await get_journal_master_key_for_encryption(
            itgs, user_sub=user_sub, now=time.time()
        )
        if master_key.type != "success":
            await handle_warning(
                f"{__name__}:master_key:{master_key.type}",
                "Failed to get master key for storing v96 onboarding survey data",
            )
        else:
            user_tz = await get_user_timezone(itgs, user_sub=user_sub)
            new_llm_context_uid = f"oseh_ullm_{secrets.token_urlsafe(16)}"
            new_llm_context_created_at = time.time()
            unix_date_for_user = unix_dates.unix_timestamp_to_unix_date(
                new_llm_context_created_at, tz=user_tz
            )
            local_time_for_user = datetime.datetime.fromtimestamp(
                new_llm_context_created_at, pytz.utc
            ).astimezone(user_tz)
            local_time_seconds_from_midnight = (
                local_time_for_user.hour * 3600
                + local_time_for_user.minute * 60
                + local_time_for_user.second
            )

            conn = await itgs.conn()
            cursor = conn.cursor()
            response = await cursor.executemany3(
                (
                    (
                        """
DELETE FROM user_llm_context
WHERE
    user_id = (SELECT users.id FROM users WHERE users.sub = ?)
    AND user_llm_context.type = 'onboarding_v96_survey'
                        """,
                        [user_sub],
                    ),
                    (
                        """
INSERT INTO user_llm_context (
    uid,
    user_id,
    type,
    user_journal_master_key_id,
    encrypted_structured_data,
    encrypted_unstructured_data,
    created_at,
    created_unix_date,
    created_local_time
)
SELECT
    ?,
    users.id,
    'onboarding_v96_survey',
    user_journal_master_keys.id,
    ?,
    ?,
    ?,
    ?,
    ?
FROM users, user_journal_master_keys
WHERE
    users.sub = ?
    AND users.id = user_journal_master_keys.user_id
    AND user_journal_master_keys.uid = ?
                        """,
                        [
                            new_llm_context_uid,
                            master_key.journal_master_key.encrypt_at_time(
                                json.dumps(
                                    {
                                        "emotion": emotion,
                                        "goals": goals,
                                        "challenge": challenge,
                                    }
                                ).encode("utf-8"),
                                int(new_llm_context_created_at),
                            ).decode("ascii"),
                            master_key.journal_master_key.encrypt_at_time(
                                (
                                    "<survey>"
                                    '<question author="assistant">What would you like to feel more of in your daily life?</question>'
                                    f'<answer author="user">{emotion}</answer>'
                                    '<question author="assistant">What are your goals?</question>'
                                    f'<answer author="user">{", ".join(goals)}</answer>'
                                    '<question author="assistant">What is your biggest challenge right now?</question>'
                                    f'<answer author="user">{challenge}</answer>'
                                    "</survey>"
                                ).encode("utf-8"),
                                int(new_llm_context_created_at),
                            ).decode("ascii"),
                            new_llm_context_created_at,
                            unix_date_for_user,
                            local_time_seconds_from_midnight,
                            user_sub,
                            master_key.journal_master_key_uid,
                        ],
                    ),
                )
            )

            if response[1].rows_affected != 1:
                await handle_warning(
                    f"{__name__}:llm_context:failed_to_store",
                    f"Expected 1 row affected, got {response[1].rows_affected=}",
                )

        goals_joined = ", ".join(goals)

        await enqueue_send_described_user_slack_message(
            itgs,
            message=f"{{name}} completed the onboarding v96 survey. They want to feel {emotion}. Their goals are: {goals_joined}. Their biggest challenge is {challenge.lower()}.",
            sub=std_auth_result.result.sub,
            channel="oseh_bot",
        )

        challenge_description = challenge.lower()
        if challenge_description == "managing stress":
            challenge_description = "with managing stress"
        elif challenge_description == "staying focused":
            challenge_description = "maintaining focus"
        elif challenge_description == "finding motivation":
            challenge_description = "finding motivation (the initial spark) and discipline (what keeps you going)"
        elif challenge_description == "improving sleep":
            challenge_description = "getting a good night’s sleep"
        elif challenge_description == "feeling connected to others":
            challenge_description = "with feeling disconnected from others"
        elif challenge_description == "creating time for self-care":
            challenge_description = "with creating time for self-care"

        content_parts: list = [
            {
                "type": "header",
                "value": f"We all face challenges {challenge_description}. With Oseh, you’ll find personalized support to overcome it.",
            }
        ]

        screen = await execute_pop(
            itgs,
            user_sub=std_auth_result.result.sub,
            platform=platform,
            version=version,
            expected_front_uid=screen_auth_result.result.user_client_screen_uid,
            trigger=UntrustedTrigger(
                flow_slug=args.trigger.slug,
                client_parameters={
                    "emotion": emotion,
                    "goals": goals,
                    "challenge": challenge,
                    "content": {
                        "type": "screen-text-content",
                        "version": 1,
                        "parts": content_parts,
                    },
                },
            ),
        )
        return await _realize(screen)
