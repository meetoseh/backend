import secrets
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Optional
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE
from itgs import Itgs


router = APIRouter()


class CreateDailyEventRequest(BaseModel):
    ...


class CreateDailyEventResponse(BaseModel):
    uid: str = Field(
        description="The primary stable external identifier of the new daily event"
    )
    created_at: float = Field(
        description="The time at which the daily event was created, in seconds since the epoch"
    )


@router.post(
    "/",
    response_model=CreateDailyEventResponse,
    responses=STANDARD_ERRORS_BY_CODE,
    status_code=201,
)
async def create_daily_event(
    args: CreateDailyEventRequest, authorization: Optional[str] = Header(None)
):
    """Creates a new daily event which is not scheduled to premiere and has no
    journeys.

    This endpoint requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        uid = f"oseh_de_{secrets.token_urlsafe(16)}"
        created_at = time.time()

        conn = await itgs.conn()
        cursor = conn.cursor("none")

        await cursor.execute(
            "INSERT INTO daily_events (uid, created_at) VALUES (?, ?)",
            (uid, created_at),
        )

        return Response(
            content=CreateDailyEventResponse(uid=uid, created_at=created_at).json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=201,
        )
