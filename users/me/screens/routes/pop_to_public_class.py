import secrets
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from journeys.lib.notifs import on_entering_lobby
from journeys.models.series_flags import SeriesFlags
from lib.client_flows.executor import (
    ClientScreenQueuePeekInfo,
    TrustedTrigger,
    execute_peek,
    execute_pop,
)
from models import AUTHORIZATION_UNKNOWN_TOKEN, STANDARD_ERRORS_BY_CODE
from typing import Annotated, Optional
from itgs import Itgs
import auth as std_auth
from users.lib.entitlements import get_entitlement
from users.lib.streak import purge_user_streak_cache
from users.lib.timezones import get_user_timezone
import users.me.screens.auth

from users.me.screens.lib.realize_screens import realize_screens
from users.me.screens.models.peeked_screen import PeekScreenResponse
from visitors.lib.get_or_create_visitor import VisitorSource
import unix_dates


router = APIRouter()


class PopToPublicClassParameters(BaseModel):
    journey_uid: str = Field(description="The uid of the journey to take")


class PopToPublicClassParametersTriggerRequest(BaseModel):
    slug: str = Field(description="The slug of the client flow to trigger")
    parameters: PopToPublicClassParameters = Field(
        description="The parameters to convert"
    )


class PopToPublicClassRequest(BaseModel):
    screen_jwt: str = Field(description="The JWT which lets you pop the screen")
    trigger: PopToPublicClassParametersTriggerRequest = Field(
        description=(
            "The client flow to trigger with server parameters containing the journey uid"
        ),
    )


@router.post(
    "/pop_to_public_class",
    response_model=PeekScreenResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def pop_screen_to_public_class(
    args: PopToPublicClassRequest,
    platform: VisitorSource,
    version: Optional[int] = None,
    visitor: Annotated[Optional[str], Header()] = None,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """A specialized pop endpoint which allows the user to take a class from
    those included on the classes tab. The triggered flow will have parameters

    ```json
    {"journey": "string"}
    ```

    If the class requires Oseh+ but the user doesn't have it, the
    `upgrade_longer_classes` flow is peeked instead.

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
                version=version,
                trigger=TrustedTrigger(
                    flow_slug="error_bad_auth",
                    client_parameters={},
                    server_parameters={},
                ),
            )
            return await _realize(screen)

        pro_entitlement = await get_entitlement(
            itgs, user_sub=user_sub, identifier="pro"
        )
        if pro_entitlement is None:
            return AUTHORIZATION_UNKNOWN_TOKEN

        user_tz = await get_user_timezone(itgs, user_sub=std_auth_result.result.sub)

        request_at = time.time()
        request_unix_date = unix_dates.unix_timestamp_to_unix_date(
            request_at, tz=user_tz
        )

        conn = await itgs.conn()
        cursor = conn.cursor(read_consistency="strong")

        premium_journeys_cte = f"""
premium_journeys(journey_id) AS (
    SELECT course_journeys.journey_id
    FROM course_journeys, courses
    WHERE
        course_journeys.course_id = courses.id
        AND (courses.flags & {int(SeriesFlags.JOURNEYS_IN_SERIES_ARE_PREMIUM)}) = 1
)
"""

        all_responses = await cursor.executeunified3(
            (
                (
                    """
SELECT 1 FROM users, user_journeys
WHERE
    users.sub = ?
    AND user_journeys.user_id = users.id
    AND user_journeys.created_at_unix_date = ?
LIMIT 1
                    """,
                    (user_sub, request_unix_date),
                ),
                (
                    f"""
WITH {premium_journeys_cte}
SELECT 
  EXISTS (
    SELECT 1 FROM premium_journeys
    WHERE premium_journeys.journey_id = journeys.id
  ) AS is_pro
FROM journeys
WHERE
    journeys.uid = ?
    AND journeys.deleted_at IS NULL
    AND journeys.special_category IS NULL
                    """,
                    (args.trigger.parameters.journey_uid,),
                ),
                (
                    f"""
WITH {premium_journeys_cte}
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
    AND journeys.special_category IS NULL
    AND (? = 1 OR NOT EXISTS (
        SELECT 1 FROM premium_journeys
        WHERE premium_journeys.journey_id = journeys.id
    ))
                    """,
                    (
                        f"oseh_uj_{secrets.token_urlsafe(16)}",
                        request_at,
                        request_unix_date,
                        std_auth_result.result.sub,
                        args.trigger.parameters.journey_uid,
                        int(pro_entitlement.is_active),
                    ),
                ),
            ),
        )
        had_class_today_response = all_responses[0]
        journey_exists_response = all_responses[1]
        insert_response = all_responses[2]

        if not journey_exists_response.results:
            assert (
                insert_response.rows_affected is None
                or insert_response.rows_affected < 1
            ), all_responses
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

        is_pro = bool(journey_exists_response.results[0][0])
        if is_pro and not pro_entitlement.is_active:
            assert (
                insert_response.rows_affected is None
                or insert_response.rows_affected < 1
            ), all_responses
            screen = await execute_peek(
                itgs,
                user_sub=std_auth_result.result.sub,
                platform=platform,
                version=version,
                trigger=TrustedTrigger(
                    flow_slug="upgrade_longer_classes",
                    client_parameters={},
                    server_parameters={},
                ),
            )
            return await _realize(screen)

        assert insert_response.rows_affected == 1, all_responses

        if not had_class_today_response.results:
            await purge_user_streak_cache(itgs, sub=user_sub)

        await on_entering_lobby(
            itgs,
            user_sub=std_auth_result.result.sub,
            journey_uid=args.trigger.parameters.journey_uid,
            action=f"starting the `{args.trigger.slug}` flow for a journey from the library",
        )

        screen = await execute_pop(
            itgs,
            user_sub=std_auth_result.result.sub,
            platform=platform,
            version=version,
            expected_front_uid=screen_auth_result.result.user_client_screen_uid,
            trigger=(
                TrustedTrigger(
                    flow_slug=args.trigger.slug,
                    client_parameters={},
                    server_parameters={
                        "journey": args.trigger.parameters.journey_uid,
                    },
                )
            ),
        )
        return await _realize(screen)
