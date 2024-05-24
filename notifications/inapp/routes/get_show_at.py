import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Optional
from error_middleware import handle_contextless_error
from models import STANDARD_ERRORS_BY_CODE
from itgs import Itgs
from auth import auth_any
from loguru import logger


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
    deprecated=True,
)
async def get_inapp_notification_show_at(
    args: GetInappNotificationShowAtRequest, authorization: Optional[str] = Header(None)
):
    """
    ## DEPRECATED

    This endpoint SHOULD NOT be used. It is intended to maintain support
    for older versions of the app.

    `inapp_notifications`, and the corresponding stack-based client navigation paradigm,
    have been replaced with `client_flows`.

    ## HISTORICAL

    Determines if the frontend should show the given in-app notification
    to the user at the appropriate time. This endpoint is exclusively meant to
    avoid hammering the user with the same notification, and doesn't consider
    any other context - for example, if the user already has a phone number,
    the phone number prompt should not be shown without using this endpoint
    at all.

    Requires standard authorization.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        if args.inapp_notification_uid == "oseh_ian_UWqxuftHMXtUnzn9kxnTOA":
            # hide upgrade screen for promotion 05/26/2024
            return Response(
                content=GetInappNotificationShowAtResponse(
                    show_now=False, next_show_at=None
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=200,
            )

        conn = await itgs.conn()
        cursor = conn.cursor("none")

        response = await cursor.execute(
            """
            SELECT
                inapp_notifications.minimum_repeat_interval,
                inapp_notification_users.created_at,
                inapp_notifications.user_max_created_at,
                inapp_notifications.maximum_repetitions,
                users.created_at
            FROM inapp_notifications
            JOIN users ON users.sub = ?
            LEFT OUTER JOIN inapp_notification_users ON (
                inapp_notifications.id = inapp_notification_users.inapp_notification_id
                AND users.id = inapp_notification_users.user_id
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
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=200,
            )

        minimum_repeat_interval: Optional[float] = response.results[0][0]
        last_shown_at: Optional[float] = response.results[0][1]
        user_max_created_at: Optional[float] = response.results[0][2]
        maximum_repetitions: Optional[int] = response.results[0][3]
        user_created_at: float = response.results[0][4]

        now = time.time()
        show_now: bool = True
        check_again_at: Optional[float] = None
        if minimum_repeat_interval is None:
            show_now = show_now and last_shown_at is None
        elif last_shown_at is None:
            check_again_at = now + minimum_repeat_interval
        elif last_shown_at + minimum_repeat_interval < now:
            check_again_at = now + minimum_repeat_interval
        else:
            show_now = False
            check_again_at = last_shown_at + minimum_repeat_interval

        if user_max_created_at is not None and user_created_at > user_max_created_at:
            show_now = False
            check_again_at = None

        if show_now and maximum_repetitions is not None:
            response = await cursor.execute(
                """
                SELECT COUNT(*) FROM inapp_notification_users
                WHERE
                    EXISTS (
                        SELECT 1 FROM users
                        WHERE users.id = inapp_notification_users.user_id
                          AND users.sub = ?
                    )
                    AND EXISTS (
                        SELECT 1 FROM inapp_notifications
                        WHERE
                            inapp_notifications.id = inapp_notification_users.inapp_notification_id
                            AND inapp_notifications.uid = ?
                    )
                """,
                (
                    auth_result.result.sub,
                    args.inapp_notification_uid,
                ),
            )
            assert response.results, response
            num_seen: int = response.results[0][0]
            if num_seen >= maximum_repetitions:
                show_now = False
                check_again_at = None

        logger.info(
            f"{__name__} responding with {show_now=} {check_again_at=} to {auth_result.result.sub=} with regard to {args.inapp_notification_uid=}"
        )
        return Response(
            content=GetInappNotificationShowAtResponse(
                show_now=show_now, next_show_at=check_again_at
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=200,
        )
