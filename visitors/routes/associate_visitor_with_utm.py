from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, StringConstraints
from typing import Optional, Annotated
from itgs import Itgs
from models import STANDARD_ERRORS_BY_CODE
from auth import auth_any
from visitors.lib.get_or_create_visitor import (
    VisitorSource,
    get_or_create_unsanitized_visitor,
)
from visitors.lib.push_user_association import push_visitor_association
from visitors.routes.create import CreateVisitorResponse
from .associate_visitor_with_user import push_visitor_user_association
import time


class AssociateVisitorWithUtmRequest(BaseModel):
    utm_source: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
    ] = Field()
    utm_medium: Optional[
        Annotated[
            str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
        ]
    ] = Field(None)
    utm_campaign: Optional[
        Annotated[
            str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
        ]
    ] = Field(None)
    utm_term: Optional[
        Annotated[
            str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
        ]
    ] = Field(None)
    utm_content: Optional[
        Annotated[
            str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
        ]
    ] = Field(None)


class QueuedVisitorUTM(BaseModel):
    visitor_uid: str = Field(description="The unverified visitor's unique identifier")
    utm_source: str = Field()
    utm_medium: Optional[str] = Field(None)
    utm_campaign: Optional[str] = Field(None)
    utm_term: Optional[str] = Field(None)
    utm_content: Optional[str] = Field(None)
    clicked_at: float = Field(description="When we were told of the association")


router = APIRouter()


@router.post(
    "/utms",
    status_code=202,
    response_model=CreateVisitorResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def associate_visitor_with_utm(
    args: AssociateVisitorWithUtmRequest,
    source: VisitorSource,
    visitor: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
):
    """Associates that the given visitor visited one of the clients with
    the given utm parameters.

    If the visitor is not provided, this will create a new visitor and
    associate it with the utm parameters.

    If user authorization is provided, this also associates the visitor with the
    user, which is preferable to calling both endpoints as it will ensure the
    timestamps are the same.
    """
    original_unsanitized_visitor = visitor
    del visitor

    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        clicked_at = time.time()

        sanitized_visitor = await get_or_create_unsanitized_visitor(
            itgs,
            visitor=original_unsanitized_visitor,
            source=source,
            seen_at=clicked_at,
        )

        if auth_result.result is not None:
            await push_visitor_user_association(
                itgs,
                visitor_uid=sanitized_visitor,
                user_sub=auth_result.result.sub,
                seen_at=clicked_at,
            )

        await push_visitor_utm_association(
            itgs,
            visitor_uid=sanitized_visitor,
            utm_source=args.utm_source,
            utm_medium=args.utm_medium,
            utm_campaign=args.utm_campaign,
            utm_term=args.utm_term,
            utm_content=args.utm_content,
            clicked_at=clicked_at,
        )
        return Response(
            status_code=202,
            content=CreateVisitorResponse(uid=sanitized_visitor).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )


async def push_visitor_utm_association(
    itgs: Itgs,
    *,
    utm_source: str,
    utm_medium: Optional[str],
    utm_campaign: Optional[str],
    utm_term: Optional[str],
    utm_content: Optional[str],
    visitor_uid: str,
    clicked_at: float,
) -> None:
    """Enqueues processing of the given visitor/utm association.

    Args:
        itgs (Itgs): The integrations to (re)use
        utm_source (str): The source of the utm
        utm_medium (Optional[str]): The medium of the utm
        utm_campaign (Optional[str]): The campaign of the utm
        utm_term (Optional[str]): The term of the utm
        utm_content (Optional[str]): The content of the utm
        visitor_uid (str): The visitor's unique identifier
        clicked_at (float): When the visitor clicked the link
    """
    queue_key = b"visitors:utms"
    lock_key = f"visitors:utms:{visitor_uid}:lock".encode("utf-8")
    msg = (
        QueuedVisitorUTM(
            visitor_uid=visitor_uid,
            utm_source=utm_source,
            utm_medium=utm_medium,
            utm_campaign=utm_campaign,
            utm_term=utm_term,
            utm_content=utm_content,
            clicked_at=clicked_at,
        )
        .model_dump_json()
        .encode("utf-8")
    )
    await push_visitor_association(
        itgs, queue_key=queue_key, lock_key=lock_key, msg=msg
    )
