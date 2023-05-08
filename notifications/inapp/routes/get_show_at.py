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


class GetInappNotificationShowAtRequest(BaseModel):
    inapp_notification_uid: str = Field(
        description=(
            "The unique identifier for the notification that the frontend wants "
            "to present to the user. This value should be hardcoded."
        )
    )


class GetInappNotificationShowAtResponse(BaseModel):
    show_now: bool = Field(
        description=(
            "Whether or not the notification should be shown to the user "
            "at the appropriate point in the flow. True to show, false "
            "to suppress."
        )
    )

    next_show_at: Optional[float] = Field(
        description=(
            "Regardless of if the notification should be shown now or not, this "
            "value is None if the notification should never be shown again in "
            "the future (if we actually present it now), otherwise, the earliest "
            "time that the notification should be shown again (after this one, "
            "if we actually present it now).\n\n"
            "This value is not authoritative; it is meant to be used by the "
            "client to avoid requests to this endpoint that will very likely "
            "not result in show_now being True. Thus, this can also be "
            "interpreted as the earliest time to ask again, if show_now is "
            "False."
        )
    )


@router.post(
    "/should_show",
    response_model=GetInappNotificationShowAtResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def get_inapp_notification_show_at(
    args: GetInappNotificationShowAtRequest, authorization: Optional[str] = Header(None)
):
    """Determines if the frontend should show the given in-app notification
    to the user at the appropriate time. This endpoint is exclusively meant to
    avoid hammering the user with the same notification, and doesn't consider
    any other context - for example, if the user already has a phone number,
    the phone number prompt should not be shown without using this endpoint
    at all.

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
                inapp_notifications.minimum_repeat_interval,
                inapp_notification_users.created_at
            FROM inapp_notifications
            LEFT OUTER JOIN inapp_notification_users ON (
                inapp_notifications.id = inapp_notification_users.inapp_notification_id
                AND EXISTS (
                    SELECT 1 FROM users
                    WHERE users.id = inapp_notification_users.user_id
                      AND users.sub = ?
                )
                AND NOT EXISTS (
                    SELECT 1 FROM inapp_notification_users AS ianu
                    WHERE ianu.inapp_notification_id = inapp_notifications.id
                        AND ianu.user_id = inapp_notification_users.user_id
                        AND ianu.created_at > inapp_notification_users.created_at
                )
            )
            WHERE
                inapp_notifications.uid = ?
            """,
            (
                auth_result.result.sub,
                args.inapp_notification_uid,
            ),
        )

        if not response.results:
            await handle_contextless_error(
                extra_info=f"suppressing unknown inapp notification uid {args.inapp_notification_uid} for {auth_result.result.sub}",
            )
            return Response(
                content=GetInappNotificationShowAtResponse(
                    show_now=False, next_show_at=None
                ).json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=200,
            )

        minimum_repeat_interval: Optional[float] = response.results[0][0]
        last_shown_at: Optional[float] = response.results[0][1]

        now = time.time()
        show_now = last_shown_at is None or (
            minimum_repeat_interval is not None
            and last_shown_at + minimum_repeat_interval < now
        )
        check_again_at = (
            None
            if minimum_repeat_interval is None
            else (
                now + minimum_repeat_interval
                if show_now
                else last_shown_at + minimum_repeat_interval
            )
        )
        return Response(
            content=GetInappNotificationShowAtResponse(
                show_now=show_now, next_show_at=check_again_at
            ).json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=200,
        )
