import secrets
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, StringConstraints
from typing import Annotated, Optional, Literal, cast

import pytz
from journeys.lib.link_stats import (
    JourneyShareLinksStatsPreparer,
    ViewClientFollowFailedInvalidReason,
    ViewClientFollowFailedRatelimitedReason,
    ViewClientFollowFailedServerErrorReason,
    journey_share_link_stats,
)
from journeys.lib.read_one_external import read_one_external
from journeys.models.external_journey import ExternalJourney
from journeys.models.series_flags import SeriesFlags
from models import StandardErrorResponse
from itgs import Itgs
import auth
import journeys.auth
from visitors.lib.get_or_create_visitor import check_visitor_sanity
import time
import unix_dates


router = APIRouter()


class FollowShareLinkRequest(BaseModel):
    code: Annotated[str, StringConstraints(min_length=2, max_length=255)] = Field(
        description="The code of the share link to follow"
    )


router = APIRouter()

ERROR_404_TYPES = Literal["bad_code"]
ERROR_BAD_CODE_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_404_TYPES].__pydantic_serializer__.to_json(
        StandardErrorResponse[ERROR_404_TYPES](
            type="bad_code",
            message="There is no share link with that code",
        )
    ),
    status_code=404,
    headers={"Content-Type": "application/json; charset=utf-8"},
)


ERROR_429_TYPES = Literal["too_many_requests"]
ERROR_TOO_MANY_REQUESTS_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_429_TYPES].__pydantic_serializer__.to_json(
        StandardErrorResponse[ERROR_429_TYPES](
            type="too_many_requests",
            message="You have made too many requests to follow share links recently",
        )
    ),
    status_code=429,
    headers={"Content-Type": "application/json; charset=utf-8"},
)

ERROR_503_TYPES = Literal["could_not_get_journey"]
ERROR_COULD_NOT_GET_JOURNEY = Response(
    content=StandardErrorResponse[ERROR_503_TYPES].__pydantic_serializer__.to_json(
        StandardErrorResponse[ERROR_503_TYPES](
            type="could_not_get_journey",
            message="We could not get the journey you are trying to follow",
        )
    ),
    status_code=503,
    headers={
        "Content-Type": "application/json; charset=utf-8",
        "Retry-After": "15",
    },
)


tz = pytz.timezone("America/Los_Angeles")


@router.post(
    "/follow_share_link",
    response_model=ExternalJourney,
    responses={
        "404": {
            "description": "There is no share link with that code",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        "429": {
            "description": "You have made too many requests to follow share links recently",
            "model": StandardErrorResponse[ERROR_429_TYPES],
        },
    },
)
async def follow_journey_share_link(
    args: FollowShareLinkRequest,
    authorization: Annotated[Optional[str], Header()] = None,
    visitor: Annotated[Optional[str], Header()] = None,
):
    """Determines where the given share code points to. This endpoint is
    intended as a backup flow for the web client and as the primary flow
    for native clients, and is typically referred to as phase 3 (api).

    For the web client, server-side hydration can fill this content under
    normal circumstances.

    Where available, the client SHOULD provide standard authorization and
    visitor headers.
    """
    request_at = time.time()
    request_unix_date = unix_dates.unix_timestamp_to_unix_date(request_at, tz=tz)
    async with Itgs() as itgs, journey_share_link_stats(itgs) as stats:
        auth_result = await auth.auth_any(itgs, authorization)
        cleaned_visitor = check_visitor_sanity(visitor)

        stats.incr_view_client_follow_requests(
            unix_date=request_unix_date,
            visitor_provided=cleaned_visitor is not None,
            user_provided=auth_result.success,
        )

        if resp := await handle_ratelimiting(
            itgs,
            stats,
            request_at=request_at,
            request_unix_date=request_unix_date,
            auth_result=auth_result,
            cleaned_visitor=cleaned_visitor,
        ):
            return resp

        conn = await itgs.conn()
        cursor = conn.cursor("none")
        redis = await itgs.redis()

        response = await cursor.execute(
            """
            SELECT
                journey_share_links.uid,
                journeys.uid,
                journey_subcategories.internal_name,
                users.sub
            FROM journey_share_links, journeys, journey_subcategories
            LEFT OUTER JOIN users ON users.id = journey_share_links.user_id
            WHERE
                journey_share_links.code = ?
                AND journeys.id = journey_share_links.journey_id
                AND journeys.deleted_at IS NULL
                AND journeys.special_category IS NULL
                AND NOT EXISTS (
                    SELECT 1 FROM course_journeys, courses
                    WHERE 
                        course_journeys.journey_id = journeys.id
                        AND course_journeys.course_id = courses.id
                        AND (courses.flags & ?) = 0
                )
                AND journey_subcategories.id = journeys.journey_subcategory_id
            """,
            (args.code, SeriesFlags.JOURNEYS_IN_SERIES_CODE_SHAREABLE),
        )

        if not response.results:
            ratelimiting_applies = await redis.set(
                f"journey_share_links:known_bad_code:{args.code}".encode("utf-8"),
                b"1",
                nx=True,
                ex=600,
            )
            assert isinstance(
                ratelimiting_applies, (bool, type(None))
            ), f"{ratelimiting_applies=}"
            if ratelimiting_applies:
                incr_ratelimiting_on_bad_code(
                    stats,
                    request_at=request_at,
                    auth_result=auth_result,
                    cleaned_visitor=cleaned_visitor,
                )
            stats.incr_view_client_follow_failed(
                unix_date=request_unix_date,
                reason=ViewClientFollowFailedInvalidReason(
                    ratelimiting_applies=not not ratelimiting_applies
                ),
            )
            return ERROR_BAD_CODE_RESPONSE

        journey_share_link_uid = cast(str, response.results[0][0])
        journey_uid = cast(str, response.results[0][1])
        journey_subcategory_internal_name = cast(str, response.results[0][2])
        sharer_sub = cast(Optional[str], response.results[0][3])

        journey_jwt = await journeys.auth.create_jwt(itgs, journey_uid=journey_uid)
        journey = await read_one_external(
            itgs,
            journey_uid=journey_uid,
            jwt=journey_jwt,
        )
        if journey is None:
            stats.incr_view_client_follow_failed(
                unix_date=request_unix_date,
                reason=ViewClientFollowFailedServerErrorReason(),
            )
            return ERROR_COULD_NOT_GET_JOURNEY

        view_uid = f"oseh_jslv_{secrets.token_urlsafe(16)}"
        async with redis.pipeline() as pipe:
            pipe.multi()
            await pipe.hset(
                f"journey_share_links:views:{view_uid}".encode("utf-8"),  # type: ignore
                mapping={
                    b"uid": view_uid,
                    b"journey_share_link_code": args.code.encode("utf-8"),
                    b"journey_share_link_uid": journey_share_link_uid.encode("utf-8"),
                    b"user_sub": auth_result.result.sub.encode("utf-8")
                    if auth_result.result is not None
                    else b"",
                    b"visitor": cleaned_visitor.encode("utf-8")
                    if cleaned_visitor is not None
                    else b"",
                    b"clicked_at": str(request_at).encode("utf-8"),
                    b"confirmed_at": str(request_at).encode("utf-8"),
                },
            )
            await pipe.rpush(
                b"journey_share_links:views_to_log", view_uid.encode("utf-8")  # type: ignore
            )
            await pipe.execute()  # type: ignore

        stats.incr_view_client_followed(
            unix_date=request_unix_date,
            journey_subcategory_internal_name=journey_subcategory_internal_name,
        )
        if cleaned_visitor is not None:
            await stats.incr_immediately_journey_share_link_unique_views(
                itgs=itgs,
                unix_date=request_unix_date,
                visitor_uid=cleaned_visitor,
                journey_subcategory_internal_name=journey_subcategory_internal_name,
                code=args.code,
                sharer_sub=sharer_sub,
                view_uid=view_uid,
            )

        return journey


async def handle_ratelimiting(
    itgs: Itgs,
    stats: JourneyShareLinksStatsPreparer,
    /,
    *,
    request_at: float,
    request_unix_date: int,
    auth_result: auth.AuthResult,
    cleaned_visitor: Optional[str],
) -> Optional[Response]:
    ratelimiting_prefix = "journey_share_links:ratelimiting"
    ratelimiting_1m_bucket = f"1m:{int(request_at) // 60}"
    ratelimiting_10m_bucket = f"10m:{int(request_at) // 600}"

    redis = await itgs.redis()
    async with redis.pipeline() as pipe:
        if cleaned_visitor is not None:
            suffix = f"invalid_confirmed_with_visitor-{cleaned_visitor}"
            await pipe.get(
                f"{ratelimiting_prefix}:{ratelimiting_1m_bucket}:{suffix}".encode(
                    "utf-8"
                )
            )
            await pipe.get(
                f"{ratelimiting_prefix}:{ratelimiting_10m_bucket}:{suffix}".encode(
                    "utf-8"
                )
            )
        if auth_result.result is not None:
            suffix = f"invalid_confirmed_with_user-{auth_result.result.sub}"
            await pipe.get(
                f"{ratelimiting_prefix}:{ratelimiting_1m_bucket}:{suffix}".encode(
                    "utf-8"
                )
            )
            await pipe.get(
                f"{ratelimiting_prefix}:{ratelimiting_10m_bucket}:{suffix}".encode(
                    "utf-8"
                )
            )

        suffix = "invalid"
        await pipe.get(
            f"{ratelimiting_prefix}:{ratelimiting_1m_bucket}:{suffix}".encode("utf-8")
        )
        await pipe.get(
            f"{ratelimiting_prefix}:{ratelimiting_10m_bucket}:{suffix}".encode("utf-8")
        )

        if auth_result.result is None:
            suffix = "invalid_confirmed_with_user"
            await pipe.get(
                f"{ratelimiting_prefix}:{ratelimiting_1m_bucket}:{suffix}".encode(
                    "utf-8"
                )
            )
            await pipe.get(
                f"{ratelimiting_prefix}:{ratelimiting_10m_bucket}:{suffix}".encode(
                    "utf-8"
                )
            )

        result = await pipe.execute()  # type: ignore

    result_idx = 0

    def next_int():
        nonlocal result_idx
        result_idx += 1
        return int(result[result_idx - 1]) if result[result_idx - 1] is not None else 0

    if cleaned_visitor is not None:
        invalid_for_visitor_last_minute = next_int()
        invalid_for_visitor_last_10_minutes = next_int()
        if invalid_for_visitor_last_minute > 3:
            stats.incr_view_client_follow_failed(
                unix_date=request_unix_date,
                reason=ViewClientFollowFailedRatelimitedReason(
                    category="visitor",
                    duration="1m",
                ),
            )
            return ERROR_TOO_MANY_REQUESTS_RESPONSE

        if invalid_for_visitor_last_10_minutes > 10:
            stats.incr_view_client_follow_failed(
                unix_date=request_unix_date,
                reason=ViewClientFollowFailedRatelimitedReason(
                    category="visitor",
                    duration="10m",
                ),
            )
            return ERROR_TOO_MANY_REQUESTS_RESPONSE

    if auth_result.result is not None:
        invalid_for_user_last_minute = next_int()
        invalid_for_user_last_10_minutes = next_int()
        if invalid_for_user_last_minute > 3:
            stats.incr_view_client_follow_failed(
                unix_date=request_unix_date,
                reason=ViewClientFollowFailedRatelimitedReason(
                    category="user",
                    duration="1m",
                ),
            )
            return ERROR_TOO_MANY_REQUESTS_RESPONSE

        if invalid_for_user_last_10_minutes > 10:
            stats.incr_view_client_follow_failed(
                unix_date=request_unix_date,
                reason=ViewClientFollowFailedRatelimitedReason(
                    category="user",
                    duration="10m",
                ),
            )
            return ERROR_TOO_MANY_REQUESTS_RESPONSE

    invalid_last_minute = next_int()
    invalid_last_10_minutes = next_int()

    if auth_result.result is None:
        invalid_confirmed_with_user_last_minute = next_int()
        invalid_confirmed_with_user_last_10_minutes = next_int()

        invalid_without_user_last_minute = (
            invalid_last_minute - invalid_confirmed_with_user_last_minute
        )
        invalid_without_user_last_10_minutes = (
            invalid_last_10_minutes - invalid_confirmed_with_user_last_10_minutes
        )

        if invalid_without_user_last_minute > 10:
            stats.incr_view_client_follow_failed(
                unix_date=request_unix_date,
                reason=ViewClientFollowFailedRatelimitedReason(
                    category="no_user",
                    duration="1m",
                ),
            )
            return ERROR_TOO_MANY_REQUESTS_RESPONSE

        if invalid_without_user_last_10_minutes > 50:
            stats.incr_view_client_follow_failed(
                unix_date=request_unix_date,
                reason=ViewClientFollowFailedRatelimitedReason(
                    category="no_user",
                    duration="10m",
                ),
            )
            return ERROR_TOO_MANY_REQUESTS_RESPONSE

    if invalid_last_minute > 60:
        stats.incr_view_client_follow_failed(
            unix_date=request_unix_date,
            reason=ViewClientFollowFailedRatelimitedReason(
                category="global",
                duration="1m",
            ),
        )
        return ERROR_TOO_MANY_REQUESTS_RESPONSE

    if invalid_last_10_minutes > 200:
        stats.incr_view_client_follow_failed(
            unix_date=request_unix_date,
            reason=ViewClientFollowFailedRatelimitedReason(
                category="global",
                duration="10m",
            ),
        )
        return ERROR_TOO_MANY_REQUESTS_RESPONSE

    return None


def incr_ratelimiting_on_bad_code(
    stats: JourneyShareLinksStatsPreparer,
    /,
    *,
    request_at: float,
    auth_result: auth.AuthResult,
    cleaned_visitor: Optional[str],
):
    for duration, duration_seconds in [
        ("1m", 60),
        ("10m", 600),
    ]:
        at = int(request_at) // duration_seconds
        expire_at = at + duration_seconds + 60 * 30
        stats.incr_ratelimiting(
            duration=duration, at=at, category="invalid", expire_at=expire_at
        )
        stats.incr_ratelimiting(
            duration=duration, at=at, category="invalid_confirmed", expire_at=expire_at
        )
        if cleaned_visitor is not None:
            stats.incr_ratelimiting(
                duration=duration,
                at=at,
                category=f"invalid_confirmed_with_visitor-{cleaned_visitor}",
                expire_at=expire_at,
            )
        if auth_result.result is not None:
            stats.incr_ratelimiting(
                duration=duration,
                at=at,
                category="invalid_confirmed_with_user",
                expire_at=expire_at,
            )
            stats.incr_ratelimiting(
                duration=duration,
                at=at,
                category=f"invalid_confirmed_with_user-{auth_result.result.sub}",
                expire_at=expire_at,
            )
