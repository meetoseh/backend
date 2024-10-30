import secrets
import socket
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal, Optional
from auth import auth_any
from itgs import Itgs
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
import time
import os

router = APIRouter()


class StoreVipChatRequestActionRequest(BaseModel):
    uid: str = Field(description="The UID of the vip chat request that's shown")
    action: Literal["open", "click_cta", "click_x", "click_done", "close_window"] = (
        Field(description="The action that was performed")
    )


ERROR_404_TYPES = Literal["not_found"]


@router.post(
    "/",
    status_code=202,
    responses={
        "404": {
            "description": "The vip chat request was not found, or is for a different user",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def store_vip_chat_request_action(
    args: StoreVipChatRequestActionRequest, authorization: Optional[str] = Header(None)
):
    """Stores that the user performed the given action on the vip chat request
    with the given uid.

    Requires standard authorization.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor()

        action_uid = f"oseh_vcra_{secrets.token_urlsafe(16)}"
        now = time.time()
        response = await cursor.executemany3(
            (
                *(
                    []
                    if args.action != "open"
                    else [
                        (
                            """
                            UPDATE vip_chat_requests
                            SET popup_seen_at = ?
                            WHERE
                                uid = ?
                                AND EXISTS (
                                    SELECT 1 FROM users
                                    WHERE users.id = vip_chat_requests.user_id
                                    AND users.sub = ?
                                )
                                AND popup_seen_at IS NULL
                            """,
                            (now, args.uid, auth_result.result.sub),
                        )
                    ]
                ),
                (
                    """
                    INSERT INTO vip_chat_request_actions (
                        uid, vip_chat_request_id, action, created_at
                    )
                    SELECT
                        ?, vip_chat_requests.id, ?, ?
                    FROM vip_chat_requests
                    WHERE
                        vip_chat_requests.uid = ?
                        AND EXISTS (
                            SELECT 1 FROM users
                            WHERE users.id = vip_chat_requests.user_id
                        )
                    """,
                    (
                        action_uid,
                        args.action,
                        now,
                        args.uid,
                    ),
                ),
            )
        )

        if response[-1].rows_affected is None or response[-1].rows_affected < 1:
            return Response(
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="not_found",
                    message="The vip chat request was not found, or is for a different user",
                ).model_dump_json(),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                },
                status_code=404,
            )

        identifier = (
            f"{auth_result.result.claims['name']} ({auth_result.result.claims['email']})"
            if auth_result.result.claims is not None
            and "name" in auth_result.result.claims
            and "email" in auth_result.result.claims
            else auth_result.result.sub
        )

        slack = await itgs.slack()
        msg = f"{socket.gethostname()} {identifier} performed action {args.action} on vip chat request {args.uid}"
        if os.environ.get("ENVIRONMENT") != "dev":
            await slack.send_oseh_bot_message(msg)
        else:
            await slack.send_ops_message(msg)
        return Response(status_code=202)
