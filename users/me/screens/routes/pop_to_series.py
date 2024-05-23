from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from lib.client_flows.executor import (
    TrustedTrigger,
    execute_peek,
    execute_pop,
)
from models import STANDARD_ERRORS_BY_CODE
from typing import Annotated, Optional
from itgs import Itgs
import auth as std_auth
import users.me.screens.auth
import courses.auth

from users.me.screens.lib.realize_screens import realize_screens
from users.me.screens.models.peeked_screen import PeekScreenResponse
from visitors.lib.get_or_create_visitor import VisitorSource


router = APIRouter()


class PopToSeriesParametersSeries(BaseModel):
    uid: str = Field(description="The uid to put in the server parameters")
    jwt: str = Field(
        description="The course jwt that allows the user to access the series"
    )


class PopToSeriesParameters(BaseModel):
    series: PopToSeriesParametersSeries = Field(
        description="The series that is being checked before moving to server parameters"
    )


class PopToSeriesParametersTriggerRequest(BaseModel):
    slug: str = Field(description="The slug of the client flow to trigger")
    parameters: PopToSeriesParameters = Field(description="The parameters to convert")


class PopToSeriesRequest(BaseModel):
    screen_jwt: str = Field(description="The JWT which lets you pop the screen")
    trigger: PopToSeriesParametersTriggerRequest = Field(
        description=(
            "The client flow to trigger with server parameters set to the series uid"
        ),
    )


@router.post(
    "/pop_to_series",
    response_model=PeekScreenResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def pop_screen_to_series(
    args: PopToSeriesRequest,
    platform: VisitorSource,
    visitor: Annotated[Optional[str], Header()] = None,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """A specialized pop endpoint which validates a course JWT provides access to
    the given course UID and then triggering a flow with server parameters set to

    ```json
    {"series": "string"}
    ```

    where the string is the course UID. The flow is triggered with no client parameters.

    If the screen jwt provided is invalid or doesn't correspond to the current
    screen, the response will still have a successful status code and you will
    retrieve a valid peeked screen, though the request may have different side
    effects than expected (i.e., you might have put a forbidden page on the
    queue instead of the intended trigger). An error is only returned if the
    provided authorization header for a user is invalid.

    Requires standard authorization for a user.
    """
    async with Itgs() as itgs:
        std_auth_result = await std_auth.auth_any(itgs, authorization)
        if std_auth_result.result is None:
            return std_auth_result.error_response

        course_auth_result = await courses.auth.auth_any(
            itgs, f"bearer {args.trigger.parameters.series.jwt}"
        )

        screen_auth_result = await users.me.screens.auth.auth_any(
            itgs, args.screen_jwt, prefix=None
        )
        if (
            screen_auth_result.result is None
            or course_auth_result.result is None
            or course_auth_result.result.course_uid
            != args.trigger.parameters.series.uid
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
        else:
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
                            "series": args.trigger.parameters.series.uid
                        },
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
