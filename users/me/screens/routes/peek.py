from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Annotated, Optional
from lib.client_flows.executor import execute_peek
from users.me.screens.lib.realize_screens import realize_screens
from users.me.screens.models.peeked_screen import PeekedScreen
from models import STANDARD_ERRORS_BY_CODE
from visitors.lib.get_or_create_visitor import VisitorSource
from itgs import Itgs
import auth

router = APIRouter()


class PeekScreenResponse(BaseModel):
    visitor: str = Field(description="The new visitor UID to use")
    screen: PeekedScreen = Field(description="The screen to show or skip")


@router.post(
    "/peek",
    response_model=PeekedScreen,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def peek_screen(
    platform: VisitorSource,
    authorization: Annotated[Optional[str], Header()] = None,
    visitor: Annotated[Optional[str], Header()] = None,
):
    """Peeks the screen queue to determine which screen to show on the given
    platform.

    Requires standard authorization for a user.
    """
    async with Itgs() as itgs:
        auth_result = await auth.auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        screen = await execute_peek(
            itgs, user_sub=auth_result.result.sub, platform=platform, trigger=None
        )
        result = await realize_screens(
            itgs,
            user_sub=auth_result.result.sub,
            platform=platform,
            visitor=visitor,
            result=screen,
        )

        return Response(
            content=result.__pydantic_serializer__.to_json(result),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=200,
        )
