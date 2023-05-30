import json
import secrets
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Optional
from error_middleware import handle_contextless_error
from models import STANDARD_ERRORS_BY_CODE
from itgs import Itgs
from auth import auth_any


router = APIRouter()


class StoreInappNotificationActionRequest(BaseModel):
    inapp_notification_user_uid: str = Field(
        description="The unique identifier for the session that the action was within"
    )
    action_slug: str = Field(description="The slug of the action that was performed")
    extra: Optional[dict] = Field(
        description="Any extra data required to describe the action. Must serialize to less than 1024 characters"
    )


@router.post(
    "/store_action",
    status_code=204,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def store_inapp_notification_action(
    args: StoreInappNotificationActionRequest,
    authorization: Optional[str] = Header(None),
):
    """Stores that the authorized user has performed the given action within the
    given in-app notification session. The valid action slugs and their corresponding
    extra data are defined by the in-app notification.

    Requires standard authorization for the user associated with the session.
    """
    serd_extra = json.dumps(args.extra) if args.extra is not None else None
    if serd_extra is not None and len(serd_extra) > 1023:
        await handle_contextless_error(
            extra_info="Silently ignoring in-app notification action with extra data that is too long"
        )
        return Response(status_code=204)

    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor()

        user_action_uid = f"oseh_ianua_{secrets.token_urlsafe(16)}"
        now = time.time()
        response = await cursor.execute(
            """
            INSERT INTO inapp_notification_user_actions (
                uid, inapp_notification_user_id, inapp_notification_action_id, extra, created_at
            )
            SELECT
                ?, inapp_notification_users.id, inapp_notification_actions.id, ?, ?
            FROM inapp_notification_users, inapp_notification_actions, users
            WHERE
                inapp_notification_users.uid = ?
                AND inapp_notification_actions.inapp_notification_id = inapp_notification_users.inapp_notification_id
                AND inapp_notification_actions.slug = ?
                AND inapp_notification_users.user_id = users.id
                AND users.sub = ?
                AND (
                    SELECT COUNT(*) FROM inapp_notification_user_actions AS ianua
                    WHERE
                        ianua.inapp_notification_user_id = inapp_notification_users.id
                ) < 15
            """,
            (
                user_action_uid,
                serd_extra,
                now,
                args.inapp_notification_user_uid,
                args.action_slug,
                auth_result.result.sub,
            ),
        )

        if response.rows_affected is None or response.rows_affected < 1:
            await handle_contextless_error(
                extra_info="Silently ignoring in-app notification action: insert checks failed"
            )

        return Response(status_code=204)