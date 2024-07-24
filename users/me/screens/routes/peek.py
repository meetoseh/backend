from fastapi import APIRouter, Header
from fastapi.responses import Response
from typing import Annotated, Optional
from lib.client_flows.executor import execute_peek
from users.me.screens.lib.realize_screens import realize_screens
from models import STANDARD_ERRORS_BY_CODE
from users.me.screens.models.peeked_screen import PeekScreenResponse
from visitors.lib.get_or_create_visitor import VisitorSource
from itgs import Itgs
import auth

router = APIRouter()


@router.post(
    "/peek",
    response_model=PeekScreenResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def peek_screen(
    platform: VisitorSource,
    version: Optional[int] = None,
    authorization: Annotated[Optional[str], Header()] = None,
    visitor: Annotated[Optional[str], Header()] = None,
):
    """Peeks the screen queue to determine which screen to show on the given
    platform.

    A version code should be included in the query parameter which corresponds
    to the highest version code of the android app whose functionality the
    client meets or exceeds. Omitting this value will be treated as the highest
    version before version codes were introduced (67).

    Requires standard authorization for a user.
    """
    async with Itgs() as itgs:
        auth_result = await auth.auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        screen = await execute_peek(
            itgs,
            user_sub=auth_result.result.sub,
            platform=platform,
            version=version,
            trigger=None,
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
