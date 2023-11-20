import secrets
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal, Optional
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from itgs import Itgs
from auth import auth_any

router = APIRouter()


class StartInappNotificationRequest(BaseModel):
    inapp_notification_uid: str = Field(
        description=(
            "The unique identifier for the notification the user is being presented with. "
            "This is stable across environments (dev, staging, prod), and should be hardcoded."
        )
    )

    platform: Literal["web", "ios", "android"] = Field(
        description="The platform the user is using"
    )


class StartInappNotificationResponse(BaseModel):
    inapp_notification_user_uid: str = Field(
        description=(
            "The unique identifier for the session that was started, so that "
            "actions can be stored against it."
        )
    )


ERROR_404_TYPES = Literal["inapp_notification_not_found"]
ERROR_INAPP_NOTIFICATION_NOT_FOUND = Response(
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="inapp_notification_not_found",
        message="There is no in-app notification with that uid",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=404,
)


@router.post(
    "/start",
    response_model=StartInappNotificationResponse,
    responses={
        404: {
            "description": "The in-app notification was not found",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def start_inapp_notification(
    args: StartInappNotificationRequest, authorization: Optional[str] = Header(None)
):
    """Stores that the authorized user has been presented with the corresponding
    in-app notification. This is used to avoid presenting the same notification
    excessively to the user. This is not guarranteed to return a new session uid
    on every call.

    Requires standard authorization.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        redis = await itgs.redis()
        cache_key = f"inapp_notification_users:{auth_result.result.sub}:{args.inapp_notification_uid}".encode(
            "utf-8"
        )

        cached = await redis.get(cache_key)
        if cached is not None:
            return Response(
                content=StartInappNotificationResponse(
                    inapp_notification_user_uid=cached.decode("utf-8")
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        conn = await itgs.conn()
        cursor = conn.cursor()

        session_uid = f"oseh_ianu_{secrets.token_urlsafe(16)}"
        now = time.time()
        response = await cursor.execute(
            """
            INSERT INTO inapp_notification_users (
                uid, inapp_notification_id, user_id, platform, created_at
            )
            SELECT
                ?, inapp_notifications.id, users.id, ?, ?
            FROM inapp_notifications, users
            WHERE
                inapp_notifications.uid = ?
                AND users.sub = ?
            """,
            (
                session_uid,
                args.platform,
                now,
                args.inapp_notification_uid,
                auth_result.result.sub,
            ),
        )

        if response.rows_affected is None or response.rows_affected < 1:
            return ERROR_INAPP_NOTIFICATION_NOT_FOUND

        await redis.set(cache_key, session_uid.encode("utf-8"), ex=60 * 15)
        return Response(
            content=StartInappNotificationResponse(
                inapp_notification_user_uid=session_uid
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
