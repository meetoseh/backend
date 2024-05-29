import secrets
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
from models import STANDARD_ERRORS_BY_CODE
from typing import Annotated, Optional
from itgs import Itgs
import auth as std_auth
from personalization.lib.pipeline import select_journey
from users.lib.timezones import get_user_timezone
import users.me.screens.auth
import users.lib.entitlements
from users.me.screens.lib.realize_screens import realize_screens
from users.me.screens.models.peeked_screen import PeekScreenResponse
from visitors.lib.get_or_create_visitor import VisitorSource
import unix_dates


router = APIRouter()


class PopToEmotionClassParameters(BaseModel):
    emotion: str = Field(
        description="The emotion word that is related to the class that should be found"
    )
    premium: bool = Field(
        False,
        description="True if a premium class was requested, false for a regular class",
    )


class PopToEmotionClassParametersTriggerRequest(BaseModel):
    slug: str = Field(description="The slug of the client flow to trigger")
    parameters: PopToEmotionClassParameters = Field(
        description="The parameters to convert"
    )


class PopToEmotionClassRequest(BaseModel):
    screen_jwt: str = Field(description="The JWT which lets you pop the screen")
    trigger: PopToEmotionClassParametersTriggerRequest = Field(
        description=(
            "The client flow to trigger with server parameters set with emotion and journey"
        ),
    )


@router.post(
    "/pop_to_emotion_class",
    response_model=PeekScreenResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def pop_screen_to_emotion_class(
    args: PopToEmotionClassRequest,
    platform: VisitorSource,
    visitor: Annotated[Optional[str], Header()] = None,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """A specialized pop endpoint which can be used to start a class for a given
    emotion word. This will move the emotion to the server parameters and add
    `journey`, the uid of a journey selected for the user for that emotion.

    If the screen jwt provided is invalid or doesn't correspond to the current
    screen, the response will still have a successful status code and you will
    retrieve a valid peeked screen, though the request may have different side
    effects than expected (i.e., you might have put a forbidden page on the
    queue instead of the intended trigger). An error is only returned if the
    provided authorization header for a user is invalid.

    When successful, this endpoint counts as taking the corresponding journey
    for the users history.

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
                trigger=TrustedTrigger(
                    flow_slug="error_bad_auth",
                    client_parameters={},
                    server_parameters={},
                ),
            )
            return await _realize(screen)

        if args.trigger.parameters.premium:
            entitlement = await users.lib.entitlements.get_entitlement(
                itgs, user_sub=std_auth_result.result.sub, identifier="pro"
            )
            if entitlement is None:
                screen = await execute_peek(
                    itgs,
                    user_sub=std_auth_result.result.sub,
                    platform=platform,
                    trigger=TrustedTrigger(
                        flow_slug="error_bad_auth",
                        client_parameters={},
                        server_parameters={},
                    ),
                )
                return await _realize(screen)

            if not entitlement.is_active:
                screen = await execute_pop(
                    itgs,
                    user_sub=std_auth_result.result.sub,
                    platform=platform,
                    expected_front_uid=screen_auth_result.result.user_client_screen_uid,
                    trigger=TrustedTrigger(
                        flow_slug="upgrade_longer_classes",
                        client_parameters={},
                        server_parameters={},
                    ),
                )
                return await _realize(screen)

        journey_uid = await select_journey(
            itgs,
            emotion=args.trigger.parameters.emotion,
            user_sub=std_auth_result.result.sub,
            premium=args.trigger.parameters.premium,
        )
        if journey_uid is None:
            screen = await execute_peek(
                itgs,
                user_sub=std_auth_result.result.sub,
                platform=platform,
                trigger=TrustedTrigger(
                    flow_slug="error_bad_auth",
                    client_parameters={},
                    server_parameters={},
                ),
            )
            return await _realize(screen)

        user_tz = await get_user_timezone(itgs, user_sub=std_auth_result.result.sub)

        request_at = time.time()
        request_unix_date = unix_dates.unix_timestamp_to_unix_date(
            request_at, tz=user_tz
        )

        conn = await itgs.conn()
        cursor = conn.cursor()

        response = await cursor.execute(
            """
INSERT INTO user_journeys (
uid, user_id, journey_id, created_at, created_at_unix_date
)
SELECT
?, users.id, journeys.id, ?, ?
FROM users, journeys
WHERE
users.sub = ?
AND journeys.uid = ?
AND journeys.deleted_at IS NULL
            """,
            (
                f"oseh_uj_{secrets.token_urlsafe(16)}",
                request_at,
                request_unix_date,
                std_auth_result.result.sub,
                journey_uid,
            ),
        )
        if response.rows_affected is None or response.rows_affected < 1:
            screen = await execute_peek(
                itgs,
                user_sub=std_auth_result.result.sub,
                platform=platform,
                trigger=TrustedTrigger(
                    flow_slug="error_bad_auth",
                    client_parameters={},
                    server_parameters={},
                ),
            )
            return await _realize(screen)

        screen = await execute_pop(
            itgs,
            user_sub=std_auth_result.result.sub,
            platform=platform,
            expected_front_uid=screen_auth_result.result.user_client_screen_uid,
            trigger=(
                TrustedTrigger(
                    flow_slug=args.trigger.slug,
                    client_parameters={},
                    server_parameters={
                        "journey": journey_uid,
                        "emotion": args.trigger.parameters.emotion,
                    },
                )
            ),
        )
        return await _realize(screen)
