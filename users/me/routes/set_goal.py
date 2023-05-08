from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal, Optional
from error_middleware import handle_contextless_error
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from auth import auth_any
from itgs import Itgs
import time


router = APIRouter()


class SetUserGoalRequest(BaseModel):
    days_per_week: int = Field(
        description="How many days per week the user wants to practice", ge=1, le=7
    )


ERROR_503_TYPES = Literal["failed_to_store"]
ERROR_FAILED_TO_STORE = Response(
    content=StandardErrorResponse[ERROR_503_TYPES](
        type="failed_to_store",
        message="Failed to update your goal, perhaps because your account has been deleted. Try again later.",
    ).json(),
    headers={"Content-Type": "application/json; charset=utf-8", "Retry-After": "5"},
    status_code=503,
)


@router.post("/goal", status_code=204, responses=STANDARD_ERRORS_BY_CODE)
async def set_user_goal(
    args: SetUserGoalRequest, authorization: Optional[str] = Header(None)
):
    """Updates the users goal, i.e., how many days per week they want to practice."""
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor()

        now = time.time()
        response = await cursor.execute(
            """
            INSERT INTO user_goals (
                user_id, days_per_week, updated_at, created_at
            )
            SELECT
                users.id, ?, ?, ?
            FROM users
            WHERE users.sub = ?
            ON CONFLICT (user_id) 
            DO UPDATE SET
                days_per_week = ?,
                updated_at = ?
            """,
            (
                args.days_per_week,
                now,
                now,
                auth_result.result.sub,
                args.days_per_week,
                now,
            ),
        )

        if response.rows_affected is None or response.rows_affected < 1:
            await handle_contextless_error(
                extra_info=f"no rows affected setting user goal: {auth_result.result.sub}, {args.days_per_week}, {now}"
            )
            return ERROR_FAILED_TO_STORE

        return Response(status_code=204)
