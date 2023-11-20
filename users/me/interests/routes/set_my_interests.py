import json
import secrets
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, validator
from typing import List, Literal, Optional
from models import StandardErrorResponse, STANDARD_ERRORS_BY_CODE
from auth import auth_any
from visitors.lib.get_or_create_visitor import (
    get_or_create_unsanitized_visitor,
    VisitorSource,
)
from visitors.routes.associate_visitor_with_user import push_visitor_user_association
from itgs import Itgs
from resources.uids import is_safe_uid
from users.me.interests.routes.read_my_interests import ReadMyInterestsResponse
from utms.lib.parse import get_canonical_utm_representation


router = APIRouter()


class SetInterestReasonUTM(BaseModel):
    type: Literal["utm"] = Field(description="The type of the reason")
    source: str = Field(description="UTM source", min_length=1, max_length=255)
    medium: Optional[str] = Field(None, description="UTM medium", max_length=255)
    campaign: Optional[str] = Field(None, description="UTM campaign", max_length=255)
    term: Optional[str] = Field(None, description="UTM term", max_length=255)
    content: Optional[str] = Field(None, description="UTM content", max_length=255)


SetInterestReason = SetInterestReasonUTM


def to_database_add_reason(reason: SetInterestReason) -> str:
    return json.dumps(
        {
            "type": "utm",
            "utm": get_canonical_utm_representation(
                utm_source=reason.source,
                utm_medium=reason.medium,
                utm_campaign=reason.campaign,
                utm_term=reason.term,
                utm_content=reason.content,
            ),
        }
    )


class SetMyInterestsRequest(BaseModel):
    reason: SetInterestReason = Field(
        description="The reason for this call. This is used for analytics purposes."
    )

    primary_interest: str = Field(
        description=(
            "The slug of the primary interest to associate with the user. This "
            "must be included in the interests list, and if it is not valid the "
            "request will fail with a 404."
        )
    )

    interests: List[str] = Field(
        description=(
            "The slugs of the interests to set for the user. Any unrecognized "
            "interests will be dropped, unless the primary interest is not "
            "recognized, in which case the request will fail with a 404. This "
            "must include the primary interest and contain only unique values."
        ),
        min_length=1,
        max_length=10,
    )

    source: VisitorSource = Field(
        description=("The source of the request, in case a visitor needs to be created")
    )

    @validator("interests")
    def interests_must_include_primary_interest(cls, v, values):
        if values.get("primary_interest") is not None:
            if values["primary_interest"] not in v:
                raise ValueError("interests must include primary_interest")
        return v

    @validator("interests", each_item=True)
    def interests_must_be_sluglike(cls, v):
        if not is_safe_uid(v):
            raise ValueError("interests must be reasonably short and url-safe")
        return v


ERROR_404_TYPES = Literal["unrecognized_primary_interest"]
UNRECOGNIZED_PRIMARY_INTEREST_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="unrecognized_primary_interest",
        message="The primary interest was not recognized.",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=404,
)


@router.post(
    "/",
    response_model=ReadMyInterestsResponse,
    responses={
        "404": {
            "description": "The primary interest was not recognized.",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def set_my_interests(
    args: SetMyInterestsRequest,
    authorization: Optional[str] = Header(None),
    visitor: Optional[str] = Header(None),
):
    """Sets the active interests for the authorized user or visitor. If the visitor
    creates an account, the interests will eventually be copied over to the user without
    any additional requests required, however, if the visitor signs into an existing
    account the interests must be copied over explicitly by the front-end if doing so
    is desired.

    Returns the new active interests for the user/visitor, which will filter out
    unrecognized interests. If the primary interest is not recognized, the request
    will fail with a 404.

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
            itgs, visitor=visitor, source=args.source, seen_at=request_at
        )

        if auth_result.result is not None:
            await push_visitor_user_association(
                itgs,
                visitor_uid=visitor,
                user_sub=auth_result.result.sub,
                seen_at=request_at,
            )

        conn = await itgs.conn()
        cursor = conn.cursor()

        if auth_result.result is not None:
            new_uids = [
                f"oseh_uint_{secrets.token_urlsafe(16)}" for _ in args.interests
            ]
            primary_uid = new_uids[args.interests.index(args.primary_interest)]
            bonus_interests_qmarks = ",".join(["(?,?)"] * len(args.interests))
            bonus_interests_values = [
                v
                for uid, interest in zip(new_uids, args.interests)
                for v in (uid, interest)
                if interest != args.primary_interest
            ]
            response = await cursor.executemany3(
                (
                    (
                        """
                        UPDATE user_interests
                        SET
                            deleted_reason = ?, deleted_at = ?
                        WHERE
                            EXISTS (
                                SELECT 1 FROM users
                                WHERE
                                    users.id = user_interests.user_id
                                    AND users.sub = ?
                            )
                            AND EXISTS (
                                SELECT 1 FROM interests
                                WHERE interests.slug = ?
                            )
                        """,
                        (
                            json.dumps({"type": "replaced"}),
                            request_at,
                            auth_result.result.sub,
                            args.primary_interest,
                        ),
                    ),
                    (
                        """
                        INSERT INTO user_interests (
                            uid, user_id, interest_id, is_primary, add_reason, created_at
                        )
                        SELECT
                            ?, users.id, interests.id, 1, ?, ?
                        FROM users, interests
                        WHERE
                            users.sub = ?
                            AND interests.slug = ?
                        """,
                        (
                            primary_uid,
                            to_database_add_reason(args.reason),
                            request_at,
                            auth_result.result.sub,
                            args.primary_interest,
                        ),
                    ),
                    *(
                        []
                        if len(args.interests) == 1
                        else [
                            (
                                f"""
                                WITH new_interests (uid, slug) AS (
                                    VALUES {bonus_interests_qmarks}
                                )
                                INSERT INTO user_interests (
                                    uid, user_id, interest_id, is_primary, add_reason, created_at
                                )
                                SELECT
                                    new_interests.uid,
                                    users.id,
                                    interests.slug,
                                    0,
                                    ?,
                                    ?
                                FROM new_interests, users, interests
                                WHERE
                                    users.sub = ?
                                    AND interests.slug = new_interests.slug
                                    AND EXISTS (SELECT 1 FROM user_interests AS ui WHERE ui.uid=?)
                                """,
                                (
                                    *bonus_interests_values,
                                    to_database_add_reason(args.reason),
                                    request_at,
                                    auth_result.result.sub,
                                    primary_uid,
                                ),
                            )
                        ]
                    ),
                )
            )
        else:
            new_uids = [f"oseh_vi_{secrets.token_urlsafe(16)}" for _ in args.interests]
            primary_uid = new_uids[args.interests.index(args.primary_interest)]
            bonus_interests_qmarks = ",".join(["(?,?)"] * len(args.interests))
            bonus_interests_values = [
                v
                for uid, interest in zip(new_uids, args.interests)
                for v in (uid, interest)
                if interest != args.primary_interest
            ]
            response = await cursor.executemany3(
                (
                    (
                        """
                        UPDATE visitor_interests
                        SET
                            deleted_reason = ?, deleted_at = ?
                        WHERE
                            EXISTS (
                                SELECT 1 FROM visitors
                                WHERE
                                    visitors.id = visitor_interests.visitor_id
                                    AND visitors.uid = ?
                            )
                            AND EXISTS (
                                SELECT 1 FROM interests
                                WHERE interests.slug = ?
                            )
                        """,
                        (
                            json.dumps({"type": "replaced"}),
                            request_at,
                            visitor,
                            args.primary_interest,
                        ),
                    ),
                    (
                        """
                        INSERT INTO visitor_interests (
                            uid, visitor_id, interest_id, is_primary, add_reason, created_at
                        )
                        SELECT
                            ?, visitors.id, interests.id, 1, ?, ?
                        FROM visitors, interests
                        WHERE
                            visitors.uid = ?
                            AND interests.slug = ?
                        """,
                        (
                            primary_uid,
                            to_database_add_reason(args.reason),
                            request_at,
                            visitor,
                            args.primary_interest,
                        ),
                    ),
                    *(
                        []
                        if len(args.interests) == 1
                        else [
                            (
                                f"""
                                WITH new_interests (uid, slug) AS (
                                    VALUES {bonus_interests_qmarks}
                                )
                                INSERT INTO visitor_interests (
                                    uid, visitor_id, interest_id, is_primary, add_reason, created_at
                                )
                                SELECT
                                    new_interests.uid,
                                    visitors.id,
                                    interests.slug,
                                    0,
                                    ?,
                                    ?
                                FROM new_interests, visitors, interests
                                WHERE
                                    visitors.uid = ?
                                    AND interests.slug = new_interests.slug
                                    AND EXISTS (SELECT 1 FROM visitor_interests AS vi WHERE vi.uid=?)
                                """,
                                (
                                    *bonus_interests_values,
                                    to_database_add_reason(args.reason),
                                    request_at,
                                    visitor,
                                    primary_uid,
                                ),
                            )
                        ]
                    ),
                )
            )

        if response[1].rows_affected is None or response[1].rows_affected < 1:
            return UNRECOGNIZED_PRIMARY_INTEREST_RESPONSE

        stored_interests = args.interests
        if (
            len(args.interests) > 1
            and response[2].rows_affected != len(args.interests) - 1
        ):
            interests_qmarks = ",".join(["?"] * len(args.interests))
            response2 = await cursor.execute(
                f"SELECT slug FROM interests WHERE slug IN ({interests_qmarks})",
                args.interests,
            )
            assert response2.results, (args.interests, interests_qmarks, response2)
            stored_interests = [row[0] for row in response2.results]

        return Response(
            content=ReadMyInterestsResponse(
                primary_interest=args.primary_interest,
                interests=stored_interests,
                visitor_uid=visitor,
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=200,
        )
