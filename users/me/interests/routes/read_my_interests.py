import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, validator
from typing import List, Optional
from models import STANDARD_ERRORS_BY_CODE
from auth import auth_any
from visitors.lib.get_or_create_visitor import (
    get_or_create_unsanitized_visitor,
    VisitorSource,
)
from visitors.routes.associate_visitor_with_user import push_visitor_user_association
from itgs import Itgs


router = APIRouter()


class ReadMyInterestsResponse(BaseModel):
    primary_interest: Optional[str] = Field(
        description=(
            "The slug of the primary interest associated with the user, "
            "or null if the user has no primary interest."
        )
    )

    interests: List[str] = Field(
        description=(
            "The list of interest slugs associated with the user; "
            "unknown slugs should be ignored. May be empty. If a primary "
            "interest is set, it will be included in this list."
        ),
        unique_items=True,
    )

    visitor_uid: str = Field(
        description="The new visitor uid to use for future requests."
    )

    @validator("interests")
    def interests_must_include_primary_interest(cls, v, values):
        if values.get("primary_interest") is not None:
            if values["primary_interest"] not in v:
                raise ValueError("interests must include primary_interest")
        return v


@router.get(
    "/", response_model=ReadMyInterestsResponse, responses=STANDARD_ERRORS_BY_CODE
)
async def read_my_interests(
    source: VisitorSource,
    authorization: Optional[str] = Header(None),
    visitor: Optional[str] = Header(None),
):
    """Returns what interests, if any, the authenticated user or visitor has.

    Standard authorization should be provided if the user is logged in, otherwise
    this uses the visitor header to associate interests. As with most visitor-enabled
    endpoints, the visitor uid may be omitted to create a new visitor uid, and
    regardless of it's provided or not, the response includes the new visitor uid
    to save, which may be the same as the one provided.
    """
    request_at = time.time()
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        visitor = await get_or_create_unsanitized_visitor(
            itgs, visitor=visitor, source=source, seen_at=request_at
        )

        if auth_result.success:
            await push_visitor_user_association(
                itgs, visitor, auth_result.result.sub, request_at
            )

        conn = await itgs.conn()
        cursor = conn.cursor("none")

        if auth_result.success:
            response = await cursor.execute(
                """
                SELECT
                    user_interests.is_primary,
                    interests.slug
                FROM user_interests, users, interests
                WHERE
                    user_interests.user_id = users.id
                    AND user_interests.interest_id = interests.id
                    AND users.sub = ?
                    AND user_interests.deleted_at IS NULL
                """,
                (auth_result.result.sub,),
            )
        else:
            response = await cursor.execute(
                """
                SELECT
                    visitor_interests.is_primary,
                    interests.slug
                FROM visitor_interests, visitors, interests
                WHERE
                    visitor_interests.visitor_id = visitors.id
                    AND visitor_interests.interest_id = interests.id
                    AND visitors.uid = ?
                    AND visitor_interests.deleted_at IS NULL
                """,
                (visitor,),
            )

        primary_interest: Optional[str] = None
        interests: List[str] = []
        for is_primary, slug in response.results or []:
            if is_primary:
                primary_interest = slug
            interests.append(slug)

        return Response(
            content=ReadMyInterestsResponse(
                primary_interest=primary_interest,
                interests=interests,
                visitor_uid=visitor,
            ).json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=200,
        )
