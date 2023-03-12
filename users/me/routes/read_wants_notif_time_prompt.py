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
                            AND user_notification_settings.channel = 'sms'
                            AND user_notification_settings.daily_event_enabled = 1
                            AND (
                                user_notification_settings.preferred_notification_time = 'any'
                                OR json_extract(user_notification_settings.timezone_technique, '$.style') = 'migration'
                            )
                    ) 
                    AND EXISTS (
                        SELECT 1 FROM phone_verifications
                        WHERE
                            EXISTS (
                                SELECT 1 FROM users
                                WHERE users.id = phone_verifications.user_id
                                    AND users.sub = ?
                            )
                            AND phone_verifications.status = 'approved'
                    )
                ) AS b1
            """,
            (auth_result.result.sub, auth_result.result.sub),
        )
        wants_notif_prompt: bool = bool(response.results[0][0])

        # this is also a good time to double check klaviyo for users which are migrating,
        # since this endpoint is primarily for migrating users who were prompted for a phone
        # number before we asked for their notification time
        jobs = await itgs.jobs()
        await jobs.enqueue(
            "runners.klaviyo.ensure_user", user_sub=auth_result.result.sub
        )

        return Response(
            content=ReadWantsNotifTimePromptResponse(
                wants_notification_time_prompt=wants_notif_prompt,
            ).json(),
            headers={
                "Content-Type": "application/json; charset=utf-8",
            },
            status_code=200,
        )
