from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Optional
from models import STANDARD_ERRORS_BY_CODE
from auth import auth_any
from itgs import Itgs


router = APIRouter()


class ReadWantsNotifTimePromptResponse(BaseModel):
    wants_notification_time_prompt: bool = Field(
        description="Whether or not the should be prompted for their notification time"
    )


@router.get(
    "/wants_notification_time_prompt",
    status_code=200,
    response_model=ReadWantsNotifTimePromptResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_wants_notif_time_prompt(authorization: Optional[str] = Header(None)):
    """Determines if the authorized user should be prompted for what time
    of day they should be notified. The client should not request this
    endpoint more than once per day.

    Requires standard authorization.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor("none")

        # TODO need a replacement for using user_notification_settings here
        # since it no logner does anything except tracking if they've set a
        # notification time, which it doesn't do super accurately
        response = await cursor.execute(
            """
            SELECT
                (
                    EXISTS (
                        SELECT 1 FROM user_notification_settings
                        WHERE
                            EXISTS (
                                SELECT 1 FROM users
                                WHERE users.id = user_notification_settings.user_id
                                    AND users.sub = ?
                            )
                            AND user_notification_settings.preferred_notification_time = 'any'
                    ) 
                ) AS b1
            """,
            (auth_result.result.sub,),
        )
        wants_notif_prompt: bool = bool(response.results[0][0])

        return Response(
            content=ReadWantsNotifTimePromptResponse(
                wants_notification_time_prompt=wants_notif_prompt,
            ).json(),
            headers={
                "Content-Type": "application/json; charset=utf-8",
            },
            status_code=200,
        )
