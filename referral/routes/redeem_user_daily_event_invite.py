import json
from fastapi import APIRouter, Header
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from typing import AsyncIterable, List, Literal, Optional, Set
from daily_events.auth import DailyEventLevel
from error_middleware import handle_error
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from daily_events.routes.now import get_current_daily_event_uid
from auth import auth_any
from daily_events.models.external_daily_event import ExternalDailyEvent
from daily_events.lib.read_one_external import (
    read_one_external as read_one_external_daily_event,
)
from daily_events.lib.has_started_one import has_started_one, on_started_one
from response_utils import cleanup_response
from journeys.models.external_journey import ExternalJourney
from journeys.lib.read_one_external import (
    read_one_external as read_one_external_journey,
)
from journeys.auth import create_jwt as create_journey_jwt
from users.lib.entitlements import get_entitlement
from itgs import Itgs
import secrets
import asyncio
import time


router = APIRouter()


class UserDailyEventInvitesRedeemRequest(BaseModel):
    code: str = Field(description="The code the sender provided")


class UserDailyEventInvitesRedeemResponse(BaseModel):
    sender_name: str = Field(description="The name of the sender")

    daily_event: Optional[ExternalDailyEvent] = Field(
        description=(
            "If the link should trigger opening a daily event, the daily event to open."
        )
    )

    journey: Optional[ExternalJourney] = Field(
        description=(
            "If the link should trigger opening a journey, the journey to open."
        )
    )

    received_oseh_plus: bool = Field(
        description="If the recipient was just granted 24 hours of oseh+"
    )


ERROR_404_TYPES = Literal["invalid_code"]
INVALID_CODE_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="invalid_code",
        message="The code provided is invalid.",
    ).json(),
    headers={"Content-Type": "application/json; charset-utf-8"},
    status_code=404,
)

ERROR_429_TYPES = Literal["too_many_requests"]
TOO_MANY_REQUESTS_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_429_TYPES](
        type="too_many_requests",
        message="You have made too many requests recently. Please try again later.",
    ).json(),
    headers={"Content-Type": "application/json; charset-utf-8"},
    status_code=429,
)

ERROR_503_TYPES = Literal["concurrent_update"]
CONCURRENT_UPDATE_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_503_TYPES](
        type="concurrent_update",
        message="There was a concurrent update to the database. Try again immediately.",
    ).json(),
    headers={"Content-Type": "application/json; charset=utf-8", "Retry-After": "1"},
    status_code=503,
)


@router.post(
    "/user_daily_event_invites/redeem",
    response_model=UserDailyEventInvitesRedeemResponse,
    responses={
        "404": {
            "description": "The code provided is invalid.",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        "429": {
            "description": "You have made too many requests recently. Please try again later.",
            "model": StandardErrorResponse[ERROR_429_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def redeem_user_daily_event_invite(
    args: UserDailyEventInvitesRedeemRequest,
    authorization: Optional[str] = Header(None),
):
    """Redeems a user daily event invite, returning potentially a deep link to the
    specific journey, as well as potentially granting the user entitlements to
    oseh+.

    This requires standard authorization via the Authorization header.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        cached_response = await get_cached_response(
            itgs, user_sub=auth_result.result.sub, code=args.code
        )
        if cached_response is not None:
            return cached_response

        redis = await itgs.redis()
        not_ratelimited = await redis.set(
            f"users:{auth_result.result.sub}:user_daily_event_invites:ratelimit".encode(
                "utf-8"
            ),
            b"1",
            nx=True,
            ex=30,
        )
        if not not_ratelimited:
            return TOO_MANY_REQUESTS_RESPONSE

        # optimistic insert -> query -> (optional insert for journey session) -> (optional update to indicate gave pro)
        conn = await itgs.conn()
        cursor = conn.cursor("weak")

        uid = f"oseh_udeir_{secrets.token_urlsafe(16)}"
        redeemed_at = time.time()

        current_daily_event_uid = await get_current_daily_event_uid(
            itgs, now=redeemed_at
        )

        response = await cursor.execute(
            """
            INSERT INTO user_daily_event_invite_recipients (
                uid, user_daily_event_invite_id, recipient_user_id, was_valid,
                was_deep_link, eligible_for_oseh_plus, received_oseh_plus,
                created_at
            )
            SELECT
                ?, 
                user_daily_event_invites.id, 
                users.id,
                EXISTS (
                    SELECT 1 FROM daily_events
                    WHERE daily_events.id = user_daily_event_invites.daily_event_id
                      AND daily_events.uid = ?
                ),
                (
                    user_daily_event_invites.journey_id IS NOT NULL
                    AND EXISTS (
                        SELECT 1 FROM daily_event_journeys
                        WHERE daily_event_journeys.daily_event_id = user_daily_event_invites.daily_event_id
                          AND daily_event_journeys.journey_id = user_daily_event_invites.journey_id
                    )
                    AND EXISTS (
                        SELECT 1 FROM journeys
                        WHERE journeys.id = user_daily_event_invites.journey_id
                          AND journeys.deleted_at IS NULL
                    )
                ),
                0,
                0,
                ?
            FROM user_daily_event_invites, users
            WHERE 
                user_daily_event_invites.code = ?
                AND users.sub = ?
                AND user_daily_event_invites.revoked_at IS NULL
            """,
            (
                uid,
                current_daily_event_uid,
                redeemed_at,
                args.code,
                auth_result.result.sub,
            ),
        )
        if response.rows_affected is None or response.rows_affected < 1:
            return INVALID_CODE_RESPONSE

        response = await cursor.execute(
            """
            SELECT
                user_daily_event_invite_recipients.was_valid,
                daily_events.uid,
                journeys.uid,
                sender_users.sub,
                recipient_users.revenue_cat_id,
                sender_users.given_name
            FROM user_daily_event_invite_recipients
            JOIN daily_events ON EXISTS (
                SELECT 1 FROM user_daily_event_invites
                WHERE user_daily_event_invites.id = user_daily_event_invite_recipients.user_daily_event_invite_id
                  AND user_daily_event_invites.daily_event_id = daily_events.id
            )
            JOIN users AS sender_users ON EXISTS (
                SELECT 1 FROM user_daily_event_invites
                WHERE user_daily_event_invites.id = user_daily_event_invite_recipients.user_daily_event_invite_id
                  AND user_daily_event_invites.sender_user_id = sender_users.id
            )
            JOIN users AS recipient_users ON recipient_users.id = user_daily_event_invite_recipients.recipient_user_id
            LEFT OUTER JOIN journeys ON EXISTS (
                SELECT 1 FROM user_daily_event_invites
                WHERE user_daily_event_invites.id = user_daily_event_invite_recipients.user_daily_event_invite_id
                  AND user_daily_event_invites.journey_id IS NOT NULL
                  AND user_daily_event_invites.journey_id = journeys.id
            )
            WHERE
                user_daily_event_invite_recipients.uid = ?
            """,
            (uid,),
        )
        if not response.results:
            return CONCURRENT_UPDATE_RESPONSE

        was_valid: bool = bool(response.results[0][0])
        daily_event_uid: str = response.results[0][1]
        journey_uid: Optional[str] = response.results[0][2]
        sender_user_sub: str = response.results[0][3]
        recipient_revenue_cat_id: str = response.results[0][4]
        sender_name: str = response.results[0][5]

        should_grant_oseh_plus: bool = False
        recipient_pro, sender_pro = await asyncio.gather(
            get_entitlement(itgs, user_sub=auth_result.result.sub, identifier="pro"),
            get_entitlement(itgs, user_sub=sender_user_sub, identifier="pro"),
        )
        if recipient_pro is None or sender_pro is None:
            return CONCURRENT_UPDATE_RESPONSE

        if not was_valid:
            # use the current daily event for the link, don't grant Oseh+
            daily_event_uid = current_daily_event_uid
            journey_uid = None
        else:
            should_grant_oseh_plus = (
                sender_pro.is_active and not recipient_pro.is_active
            )

            if not should_grant_oseh_plus:
                journey_uid = None

        daily_event: Optional[Response] = None
        journey: Optional[Response] = None

        if journey_uid is not None:
            jwt = await create_journey_jwt(itgs, journey_uid=journey_uid)
            journey = await read_one_external_journey(
                itgs, journey_uid=journey_uid, jwt=jwt
            )
            if journey is None:
                return CONCURRENT_UPDATE_RESPONSE

            if not recipient_pro.is_active and not should_grant_oseh_plus:
                await on_started_one(
                    itgs,
                    user_sub=auth_result.result.sub,
                    daily_event_uid=daily_event_uid,
                )
        else:
            level: Set[DailyEventLevel] = {"read", "start_none"}
            if recipient_pro.is_active or should_grant_oseh_plus:
                level = {"read", "start_full"}
            elif not await has_started_one(
                itgs, user_sub=auth_result.result.sub, daily_event_uid=daily_event_uid
            ):
                level = {"read", "start_random"}

            daily_event = await read_one_external_daily_event(
                itgs, uid=daily_event_uid, level=level
            )
            if daily_event is None:
                return CONCURRENT_UPDATE_RESPONSE

        received_oseh_plus: bool = False
        if should_grant_oseh_plus:
            try:
                revenue_cat = await itgs.revenue_cat()
                await revenue_cat.grant_promotional_entitlement(
                    revenue_cat_id=recipient_revenue_cat_id,
                    entitlement_identifier="pro",
                    duration="daily",
                )
                await get_entitlement(
                    itgs, user_sub=auth_result.result.sub, identifier="pro", force=True
                )
                received_oseh_plus = True
            except Exception as e:
                await handle_error(
                    e,
                    extra_info=f"granting pro entitlement from referral for {recipient_revenue_cat_id}",
                )

        response = StreamingResponse(
            content=iter_body_from_cached(
                daily_event, journey, received_oseh_plus, sender_name
            ),
            status_code=200,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
        )
        return await set_cached_response(
            itgs, user_sub=auth_result.result.sub, code=args.code, response=response
        )


async def iter_body_from_cached(
    daily_event: Optional[Response],
    journey: Optional[Response],
    received_oseh_plus: bool,
    sender_name: str,
) -> AsyncIterable[bytes]:
    yield b'{"received_oseh_plus":'
    if received_oseh_plus:
        yield b"true"
    else:
        yield b"false"

    yield b',"sender_name":'
    yield json.dumps(sender_name).encode("utf-8")

    yield b',"daily_event":'
    if daily_event is not None:
        if isinstance(daily_event, StreamingResponse):
            async for chunk in daily_event.body_iterator:
                yield chunk
        else:
            yield daily_event.body
    else:
        yield b"null"

    yield b',"journey":'
    if journey is not None:
        if isinstance(journey, StreamingResponse):
            async for chunk in journey.body_iterator:
                yield chunk
        else:
            yield journey.body
    else:
        yield b"null"

    yield b"}"


async def get_cached_response(
    itgs: Itgs, *, user_sub: str, code: str
) -> Optional[Response]:
    """If we've already recently handled a request from the given user redeeming
    the given code, return the cached response. This allows the user to repeat
    the request (e.g., if they refresh the page / close the tab) without having
    a weird experience.

    Args:
        itgs (Itgs): The integrations to (re)use
        user_sub (str): The user's sub
        code (str): The code to redeem
    Returns:
        Response, None: The cached response, if we have one, or None
    """
    redis = await itgs.redis()
    key = f"users:{user_sub}:user_daily_event_invites:success:{code}".encode("utf-8")

    data = await redis.get(key)
    if data is None:
        return None

    return Response(
        content=data,
        status_code=200,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Cache-Control": "no-store",
        },
    )


async def set_cached_response(
    itgs: Itgs,
    *,
    user_sub: str,
    code: str,
    response: Response,
) -> Response:
    """Caches the given response while also returning a new response with the same
    content.

    Args:
        itgs (Itgs): The integrations to (re)use
        user_sub (str): The user's sub
        code (str): The code to redeem
        response (Response): The response to cache

    Returns:
        Response: A new response with the same content
    """
    if isinstance(response, StreamingResponse):
        chunks: List[bytes] = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)
        content = b"".join(chunks)
    else:
        content = response.body

    redis = await itgs.redis()
    key = f"users:{user_sub}:user_daily_event_invites:success:{code}".encode("utf-8")
    await redis.set(key, content, ex=5 * 60)
    return Response(
        content=content,
        status_code=200,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Cache-Control": "no-store",
        },
    )
