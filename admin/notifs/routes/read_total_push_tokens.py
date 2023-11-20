from fastapi import APIRouter, Header
from fastapi.responses import Response
from typing import Optional, List, cast as typing_cast
from pydantic import BaseModel, Field
from models import STANDARD_ERRORS_BY_CODE
from auth import auth_admin
from itgs import Itgs
import time


router = APIRouter()


class ReadTotalPushTokensResponse(BaseModel):
    total_push_tokens: int = Field(
        description="The total number of push tokens in the database"
    )
    checked_at: float = Field(
        description="The time at which the total push tokens was checked, in seconds since the epoch"
    )


@router.get(
    "/total_push_tokens",
    response_model=ReadTotalPushTokensResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_total_push_tokens(authorization: Optional[str] = Header(None)):
    """Fetches the total number of Expo Push Tokens we have right now. This includes
    verified/unverified tokens, but only ones which we haven't confirmed are invalid.

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor("none")

        now = time.time()
        response = await cursor.execute("SELECT COUNT(*) from user_push_tokens")
        total_push_tokens = typing_cast(List[List[int]], response.results)[0][0]

        return Response(
            content=ReadTotalPushTokensResponse(
                total_push_tokens=total_push_tokens, checked_at=now
            ).model_dump_json(),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "private, max-age=5",
            },
        )
