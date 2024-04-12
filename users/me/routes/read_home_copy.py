from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Annotated, Optional, Literal
from auth import auth_any
from models import STANDARD_ERRORS_BY_CODE, AUTHORIZATION_UNKNOWN_TOKEN
from itgs import Itgs
from personalization.home.copy.lib.helper import get_homescreen_copy
from users.lib.timezones import TimezoneTechniqueSlug


class ReadHomeCopyResponse(BaseModel):
    headline: str = Field(
        description="The headline text, in large font at the top of the homescreen"
    )
    subheadline: str = Field(
        description="The smaller text below the headline on the homescreen"
    )


router = APIRouter()


@router.get(
    "/home_copy", response_model=ReadHomeCopyResponse, responses=STANDARD_ERRORS_BY_CODE
)
async def read_home_copy(
    variant: Literal["session_start", "session_end"],
    tz: str,
    tzt: TimezoneTechniqueSlug,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Reads the copy that should be shown on the home screen for the given user.
    This value should not be cached beyond respecting any provided cache-control
    headers.

    This is sensitive to the time of day, so to avoid inaccuracies the client
    must include their timezone and how it was determined. The timezone should
    be specified via an IANA timezone string, e.g., `America/Los_Angeles`, with
    care taken to correctly encode this as a query argument.

    NOTE:
        If it can be done without slowing the response, the server _may_ update
        the users timezone to match the value specified, but this is not
        guarranteed.

    The variant should specify if, within this session on the clients device, the user
    has not taken a class (session_start) or has taken a class (session_end).

    The response will generally be stable for some period of time.

    Requires standard authorization.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        copy = await get_homescreen_copy(
            itgs, user_sub=auth_result.result.sub, variant=variant, tz=tz, tzt=tzt
        )
        if copy is None:
            return AUTHORIZATION_UNKNOWN_TOKEN

        return Response(
            content=ReadHomeCopyResponse.__pydantic_serializer__.to_json(
                ReadHomeCopyResponse(
                    headline=copy.headline, subheadline=copy.subheadline
                )
            ),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "private, max-age=60, stale-if-error=3600",
            },
            status_code=200,
        )
