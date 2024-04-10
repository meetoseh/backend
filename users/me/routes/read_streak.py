from itgs import Itgs
from fastapi import APIRouter, Header
from fastapi.responses import Response
from typing import (
    Optional,
)
from auth import auth_any
from models import STANDARD_ERRORS_BY_CODE

from users.lib.streak import UserStreak, read_user_streak


router = APIRouter()


@router.get("/streak", response_model=UserStreak, responses=STANDARD_ERRORS_BY_CODE)
async def read_streak(authorization: Optional[str] = Header(None)):
    """Gets the authorized user current streak, i.e., how many days the
    user has attended since missing one.

    Requires standard authorization.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        result = await read_user_streak(itgs, sub=auth_result.result.sub)
        return Response(
            content=result,
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=200,
        )
