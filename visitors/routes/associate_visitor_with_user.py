from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Optional
from itgs import Itgs
from auth import auth_any
from models import STANDARD_ERRORS_BY_CODE
import time
import re
from visitors.lib.get_or_create_visitor import (
    VisitorSource,
    get_or_create_unsanitized_visitor,
)
from visitors.lib.push_user_association import push_visitor_association
from visitors.routes.create import CreateVisitorResponse


router = APIRouter()
VALID_VISITOR_UID = re.compile(r"^oseh_v_[a-zA-Z0-9_-]{5,30}$")


class QueuedVisitorUser(BaseModel):
    visitor_uid: str = Field(description="The unverified visitor's unique identifier")
    user_sub: str = Field(description="The verified user sub")
    seen_at: float = Field(description="When we were told of the association")


@router.post(
    "/users",
    status_code=202,
    response_model=CreateVisitorResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def associate_visitor_with_user(
    source: VisitorSource,
    visitor: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
):
    """Associates the given visitor with the authorized user. The client should try
    to only call this once per day per user per visitor.

    This will return the visitor uid that was processed, which may differ from
    the provided one if the one provided is invalid. This means this endpoint
    can be called even when a visitor is not available on the client. Note
    that if a utm is also available, the associate visitor with utm is also
    able to create a visitor and associate that visitor with a user in one
    request. Unlike that endpoint, this endpoint will return an error if the
    user is not authorized.

    Requires standard authorization.
    """
    original_unsanitized_visitor = visitor
    del visitor

    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        seen_at = time.time()
        sane_visitor = await get_or_create_unsanitized_visitor(
            itgs, visitor=original_unsanitized_visitor, source=source, seen_at=seen_at
        )
        await push_visitor_user_association(
            itgs, sane_visitor, auth_result.result.sub, seen_at
        )
        return Response(
            status_code=202,
            content=CreateVisitorResponse(uid=sane_visitor).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )


async def push_visitor_user_association(
    itgs: Itgs, visitor_uid: str, user_sub: str, seen_at: float
) -> None:
    """Enqueues the given visitor/user association for processing.

    Args:
        itgs (Itgs): The integrations to (re)use
        visitor_uid (str): The visitor's unique identifier
        user_sub (str): The user's sub
        seen_at (float): When we were told of the association
    """
    queue_key = b"visitors:user_associations"
    lock_key = f"visitors:user_associations:{user_sub}:lock".encode("utf-8")
    msg = (
        QueuedVisitorUser(
            visitor_uid=visitor_uid,
            user_sub=user_sub,
            seen_at=seen_at,
        )
        .model_dump_json()
        .encode("utf-8")
    )
    await push_visitor_association(
        itgs, queue_key=queue_key, lock_key=lock_key, msg=msg
    )
