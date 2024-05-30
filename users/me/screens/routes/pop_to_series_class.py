import secrets
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from journeys.lib.notifs import on_entering_lobby
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
from users.lib.streak import purge_user_streak_cache
from users.lib.timezones import get_user_timezone
import users.me.screens.auth
import courses.auth

from users.me.screens.lib.realize_screens import realize_screens
from users.me.screens.models.peeked_screen import PeekScreenResponse
from visitors.lib.get_or_create_visitor import VisitorSource
import unix_dates


router = APIRouter()


class PopToSeriesClassParametersSeries(BaseModel):
    uid: str = Field(description="The uid to put in the server parameters")
    jwt: str = Field(
        description="The course jwt that allows the user to access the series"
    )


class PopToSeriesClassParametersJourney(BaseModel):
    uid: str = Field(
        description="The uid of the journey to put in the server parameters"
    )


class PopToSeriesClassParameters(BaseModel):
    series: PopToSeriesClassParametersSeries = Field(
        description="The series that is being checked before moving to server parameters"
    )
    journey: PopToSeriesClassParametersJourney = Field(
        description="The journey within the series to put in the server parameters"
    )


class PopToSeriesClassParametersTriggerRequest(BaseModel):
    slug: str = Field(description="The slug of the client flow to trigger")
    parameters: PopToSeriesClassParameters = Field(
        description="The parameters to convert"
    )


class PopToSeriesClassRequest(BaseModel):
    screen_jwt: str = Field(description="The JWT which lets you pop the screen")
    trigger: PopToSeriesClassParametersTriggerRequest = Field(
        description=(
            "The client flow to trigger with server parameters set to the series and journey uids"
        ),
    )


@router.post(
    "/pop_to_series_class",
    response_model=PeekScreenResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def pop_screen_to_series_class(
    args: PopToSeriesClassRequest,
    platform: VisitorSource,
    visitor: Annotated[Optional[str], Header()] = None,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """A specialized pop endpoint which validates a course JWT provides access to
    the given course UID and then triggering a flow with server parameters set to

    ```json
    {"series": "string", "journey": "string"}
    ```

    with the course UID and one of the journeys within the courses uids. The
    flow is triggered with no client parameters.

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

        course_auth_result = await courses.auth.auth_any(
            itgs, f"bearer {args.trigger.parameters.series.jwt}"
        )
        screen_auth_result = await users.me.screens.auth.auth_any(
            itgs, args.screen_jwt, prefix=None
        )

        if (
            screen_auth_result.result is None
            or course_auth_result.result is None
            or (
                course_auth_result.result.course_uid
                != args.trigger.parameters.series.uid
            )
            or (
                (
                    course_auth_result.result.oseh_flags
                    & courses.auth.CourseAccessFlags.TAKE_JOURNEYS
                )
                == 0
            )
        ):
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

        response = await cursor.executeunified3(
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
                    (std_auth_result.result.sub, request_unix_date),
                ),
                (
                    """
INSERT INTO user_journeys (
    uid, user_id, journey_id, created_at, created_at_unix_date
)
SELECT
    ?, users.id, journeys.id, ?, ?
FROM users, journeys, courses, course_journeys
WHERE
    users.sub = ?
    AND journeys.uid = ?
    AND courses.uid = ?
    AND course_journeys.course_id = courses.id
    AND course_journeys.journey_id = journeys.id
    AND journeys.deleted_at IS NULL
                    """,
                    (
                        f"oseh_uj_{secrets.token_urlsafe(16)}",
                        request_at,
                        request_unix_date,
                        std_auth_result.result.sub,
                        args.trigger.parameters.journey.uid,
                        course_auth_result.result.course_uid,
                    ),
                ),
            )
        )
        if response[1].rows_affected is None or response[1].rows_affected < 1:
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

        if not response[0].results:
            await purge_user_streak_cache(itgs, sub=user_sub)

        await on_entering_lobby(
            itgs,
            user_sub=std_auth_result.result.sub,
            journey_uid=args.trigger.parameters.journey.uid,
            action=f"starting the `{args.trigger.slug}` flow for a journey in a series",
        )

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
                        "series": args.trigger.parameters.series.uid,
                        "journey": args.trigger.parameters.journey.uid,
                    },
                )
            ),
        )

        return await _realize(screen)
