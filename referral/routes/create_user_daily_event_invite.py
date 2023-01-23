from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from image_files.models import ImageFileRef
from typing import List, Literal, Optional, Set
from auth import auth_any
from itgs import Itgs
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from daily_events.routes.now import get_current_daily_event_uid
from pypika import Table, Query, Parameter
from pypika.queries import QueryBuilder
from pypika.terms import ExistsCriterion
from db.utils import TermWithParameters
from image_files.auth import create_jwt as create_image_file_jwt
import users.lib.entitlements
import secrets
import string
import time
import os


router = APIRouter()


class CreateUserDailyEventInviteRequest(BaseModel):
    journey_uid: Optional[str] = Field(
        description=(
            "If the generated link should be a deep-link into one of the journeys "
            "within the current daily event, the uid of the journey to deep link to. "
            "This may be specified even if the user doesn't have access to that journey, "
            "but the recipient will only be guarranteed access to the journey if the "
            "sender has Oseh+"
        )
    )


class DailyEventInfo(BaseModel):
    instructors: List[str] = Field(
        description="The unique instructor names who have journeys within the daily event"
    )


class DeepLinkInfo(BaseModel):
    type: Literal["journey"] = Field(description="The type of deep link")
    instructor: str = Field(description="The name of the instructor of the journey")
    title: str = Field(description="The title for the journey")
    background_image: ImageFileRef = Field(
        description="The background image for the journey"
    )


class CreateUserDailyEventInviteResponse(BaseModel):
    code: str = Field(description="The unique code for the invite")
    url: str = Field(description="The standard url with the code embedded")
    is_plus_link: bool = Field(
        description=(
            "True if the sender has Oseh+ and hence the recipient of the link "
            "will be granted 24 hours of Oseh+ if they use the link while the "
            "daily event is still active"
        )
    )
    daily_event_info: DailyEventInfo = Field(
        description="The daily event info, which may be useful for formatting the senders message"
    )
    deep_link_info: Optional[DeepLinkInfo] = Field(
        description=(
            "If this code is intended to be a 'deep link', i.e., go to "
            "a specific item within the daily event, this will be the "
            "info for that item"
        )
    )


ERROR_409_TYPES = Literal["journey_not_part_of_daily_event"]
JOURNEY_NOT_PART_OF_DAILY_EVENT_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_409_TYPES](
        type="journey_not_part_of_daily_event",
        message="The journey you are trying to create a link to is not part of the current daily event",
    ).json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=409,
)

ERROR_429_TYPES = Literal["too_many_requests"]
TOO_MANY_REQUESTS_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_429_TYPES](
        type="too_many_requests",
        message="You are doing that too much. Try again in a little bit.",
    ).json(),
    headers={"Content-Type": "application/json; charset=utf-8", "Retry-After": "5"},
    status_code=429,
)

ERROR_503_TYPES = Literal["no_daily_event", "concurrent_update"]
NO_DAILY_EVENT_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_503_TYPES](
        type="no_daily_event",
        message="There is no daily event currently active",
    ).json(),
    headers={"Content-Type": "application/json; charset=utf-8", "Retry-After": "300"},
    status_code=503,
)
CONCURRENT_UPDATE_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_503_TYPES](
        type="concurrent_update",
        message="There was a concurrent update to the database. Try again immediately.",
    ).json(),
    headers={"Content-Type": "application/json; charset=utf-8", "Retry-After": "1"},
    status_code=503,
)


@router.post(
    "/user_daily_event_invites/",
    response_model=CreateUserDailyEventInviteResponse,
    status_code=200,
    responses={
        "409": {
            "description": "The journey you are trying to create a link to is not part of the current daily event",
            "model": StandardErrorResponse[ERROR_409_TYPES],
        },
        "429": {
            "description": "Too many requests in a short period of time. Try again in a few seconds.",
            "model": StandardErrorResponse[ERROR_429_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def create_user_daily_event_invite(
    args: CreateUserDailyEventInviteRequest,
    authorization: Optional[str] = Header(None),
):
    """Creates a user daily event invite, returning potentially a deep link to the
    specific journey, as well as potentially granting the recipients oseh+

    This may return a previous invite rather than generating a new invite if an
    invite was just created, as invites are reusable.

    Requires standard authorization via the Authorization header
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        # happy path: insert & query [requires consistency level >= weak]
        # fallback happy path: failed insert & 1 query [requires consistency level >= none]
        # fallback unhappy path: failed insert & 2 queries [requires consistency level >= none]
        conn = await itgs.conn()
        cursor = conn.cursor("weak")

        new_uid = f"oseh_udei_{secrets.token_urlsafe(16)}"
        new_code = generate_code()
        generated_at = time.time()

        current_daily_event_uid = await get_current_daily_event_uid(
            itgs, now=generated_at
        )
        if current_daily_event_uid is None:
            return NO_DAILY_EVENT_RESPONSE

        result = await cursor.execute(
            """
            INSERT INTO user_daily_event_invites (
                uid,
                code,
                sender_user_id,
                daily_event_id,
                journey_id,
                originally_had_journey,
                created_at
            )
            SELECT
                ?, ?, users.id, daily_events.id, journeys.id, journeys.id IS NOT NULL, ?
            FROM users, daily_events
            LEFT OUTER JOIN journeys ON (
                ? IS NOT NULL 
                AND journeys.uid = ?
                AND EXISTS (
                    SELECT 1 FROM daily_event_journeys
                    WHERE daily_event_journeys.daily_event_id = daily_events.id
                      AND daily_event_journeys.journey_id = journeys.id
                )
                AND journeys.deleted_at IS NULL
            )
            WHERE
                users.sub = ?
                AND daily_events.uid = ?
                AND NOT EXISTS (
                    SELECT 1 FROM user_daily_event_invites AS udei
                    WHERE udei.sender_user_id = users.id
                      AND udei.daily_event_id = daily_events.id
                      AND (
                        (udei.journey_id IS NULL AND journeys.id IS NULL)
                        OR udei.journey_id = journeys.id
                      )
                      AND udei.created_at > ?
                )
            """,
            (
                new_uid,
                new_code,
                generated_at,
                args.journey_uid,
                args.journey_uid,
                auth_result.result.sub,
                current_daily_event_uid,
                generated_at - 3600,
            ),
        )
        if result.rows_affected is not None and result.rows_affected > 0:
            content = await get_response_content_for_row(
                itgs,
                user_sub=auth_result.result.sub,
                term=TermWithParameters(
                    term=(
                        Table("user_daily_event_invites").field("uid") == Parameter("?")
                    ),
                    parameters=(new_uid,),
                ),
                consistency_level="weak",
            )
            if content is None:
                return CONCURRENT_UPDATE_RESPONSE

            return Response(
                content=content.json(),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Cache-Control": "private, max-age=30",
                },
                status_code=200,
            )

        user_daily_event_invites = Table("user_daily_event_invites")
        daily_events = Table("daily_events", alias="term_daily_events")
        journeys = Table("journeys", alias="term_journeys")
        sender_users = Table("users", alias="term_sender_users")
        content = await get_response_content_for_row(
            itgs,
            user_sub=auth_result.result.sub,
            term=TermWithParameters(
                term=(
                    ExistsCriterion(
                        Query.from_(sender_users)
                        .select(1)
                        .where(
                            sender_users.id == user_daily_event_invites.sender_user_id
                        )
                        .where(sender_users.sub == Parameter("?"))
                    )
                    & ExistsCriterion(
                        Query.from_(daily_events)
                        .select(1)
                        .where(
                            daily_events.id == user_daily_event_invites.daily_event_id
                        )
                        .where(daily_events.uid == Parameter("?"))
                    )
                    & (
                        user_daily_event_invites.field("journey_id").isnull()
                        if args.journey_uid is None
                        else ExistsCriterion(
                            Query.from_(journeys)
                            .select(1)
                            .where(journeys.id == user_daily_event_invites.journey_id)
                            .where(journeys.uid == Parameter("?"))
                            .where(journeys.deleted_at.isnull())
                        )
                    )
                    & (user_daily_event_invites.created_at > Parameter("?"))
                ),
                parameters=[
                    auth_result.result.sub,
                    current_daily_event_uid,
                    *([args.journey_uid] if args.journey_uid is not None else []),
                    generated_at - 3600,
                ],
            ),
            consistency_level="none",
        )
        if content is None:
            if args.journey_uid is not None:
                cursor = conn.cursor("none")
                response = await cursor.execute(
                    """
                    SELECT 1 FROM journeys
                    WHERE
                        EXISTS (
                            SELECT 1 FROM daily_event_journeys
                            WHERE
                                EXISTS (
                                    SELECT 1 FROM daily_events
                                    WHERE daily_events.id = daily_event_journeys.daily_event_id
                                    AND daily_events.uid = ?
                                )
                                AND daily_event_journeys.journey_id = journeys.id
                        )
                        AND journeys.uid = ?
                        AND journeys.deleted_at IS NULL
                    """,
                    (current_daily_event_uid, args.journey_uid),
                )
                if not response.results:
                    return JOURNEY_NOT_PART_OF_DAILY_EVENT_RESPONSE

            return CONCURRENT_UPDATE_RESPONSE

        return Response(
            content=content.json(),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "private, max-age=30",
            },
            status_code=200,
        )


# RFC 3986 2.3. Unreserved Characters
# Updated by:
# - RFC 6874: Proposed Standard - no apparent relevant change
# - RFC 7320 aka BCP 190: Best Current Practice - no apparent relevant change
# - RFC 8820: Best Current Practice - no apparent relevant change
CODE_ALPHABET = string.ascii_letters + string.digits + "-._~"


def generate_code() -> str:
    """Generates a random url-safe code. This has
    66^5 ~= 1.25 billion possible values and thus collisions are
    highly unlikely.

    Note that the returned result may not be a valid base64
    string.
    """
    return "".join([secrets.choice(CODE_ALPHABET) for _ in range(5)])


async def get_response_content_for_row(
    itgs: Itgs,
    *,
    user_sub: str,
    term: TermWithParameters,
    consistency_level: Literal["none", "weak", "strong"],
) -> Optional[CreateUserDailyEventInviteResponse]:
    """Gets the response content for the user daily event invite matching
    the given term with parameters, if it could be found, otherwise returns None.

    Args:
        itgs (Itgs): The integrations to (re)use
        user_sub (str): The sub of the user the invite is for; used to extract
            entitlement information
        term (TermWithParameters): The term to use to find the invite, with
            optional structured parameters.

    Returns:
        CreateUserDailyEventInviteResponse, None: If a row was found, the content
            for the response, otherwise None
    """
    user_daily_event_invites = Table("user_daily_event_invites")
    daily_event_journeys = Table("daily_event_journeys")
    journeys = Table("journeys")
    instructors = Table("instructors")
    image_files = Table("image_files")

    query: QueryBuilder = (
        Query.from_(user_daily_event_invites)
        .select(
            user_daily_event_invites.code,
            user_daily_event_invites.journey_id,
            journeys.id,
            journeys.title,
            image_files.uid,
            instructors.name,
        )
        .join(journeys)
        .on(
            ExistsCriterion(
                Query.from_(daily_event_journeys)
                .select(1)
                .where(
                    user_daily_event_invites.daily_event_id
                    == daily_event_journeys.daily_event_id,
                )
                .where(
                    journeys.id == daily_event_journeys.journey_id,
                )
            )
        )
        .join(image_files)
        .on(image_files.id == journeys.background_image_file_id)
        .join(instructors)
        .on(instructors.id == journeys.instructor_id)
        .where(term.term)
    )
    qargs = term.parameters

    conn = await itgs.conn()
    cursor = conn.cursor(consistency_level)

    response = await cursor.execute(query.get_sql(), qargs)
    if not response.results:
        return None

    code: str = response.results[0][0]
    deep_link_journey_id: Optional[int] = response.results[0][1]

    daily_event_instructor_names: Set[str] = set()
    deep_link_instructor_name: Optional[str] = None
    deep_link_title: Optional[str] = None
    deep_link_image_uid: Optional[str] = None

    for row in response.results:
        row_journey_id: int = row[2]
        row_title: str = row[3]
        row_image_file_uid: str = row[4]
        row_instructor_name: str = row[5]

        daily_event_instructor_names.add(row_instructor_name)
        if row_journey_id == deep_link_journey_id:
            deep_link_instructor_name = row_instructor_name
            deep_link_title = row_title
            deep_link_image_uid = row_image_file_uid

    has_pro = await users.lib.entitlements.get_entitlement(
        itgs, user_sub=user_sub, identifier="pro"
    )

    return CreateUserDailyEventInviteResponse(
        code=code,
        url=os.environ["ROOT_FRONTEND_URL"] + "/i/" + code,
        is_plus_link=has_pro is not None and has_pro.is_active,
        daily_event_info=DailyEventInfo(
            instructors=list(daily_event_instructor_names),
        ),
        deep_link_info=(
            None
            if deep_link_instructor_name is None
            else DeepLinkInfo(
                type="journey",
                instructor=deep_link_instructor_name,
                title=deep_link_title,
                background_image=ImageFileRef(
                    uid=deep_link_image_uid,
                    jwt=await create_image_file_jwt(itgs, deep_link_image_uid),
                ),
            )
        ),
    )
