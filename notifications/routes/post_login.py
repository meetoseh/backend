from typing import Optional
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from auth import auth_any
from itgs import Itgs
from lib.touch.links import click_link
from models import STANDARD_ERRORS_BY_CODE


class PostLoginNotificationRequest(BaseModel):
    code: str = Field(
        description="The code sent to the user", min_length=1, max_length=255
    )
    uid: str = Field(
        description="The UID returned by the complete notification route",
        min_length=1,
        max_length=255,
    )


router = APIRouter()


@router.post("/post_login", responses=STANDARD_ERRORS_BY_CODE, status_code=202)
async def on_post_login(
    args: PostLoginNotificationRequest,
    visitor: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
):
    """Should be called after an on_click event if the user logs in right
    after to update the user which clicked the link. Knowing that users
    are/aren't sharing links improves our ability to send security alerts.

    Requires standard authorization.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        await click_link(
            itgs,
            code=args.code,
            visitor_uid=visitor,
            user_sub=auth_result.result.sub,
            track_type="post_login",
            parent_uid=args.uid,
            clicked_at=None,
            should_track=True,
        )
        return Response(status_code=202)
