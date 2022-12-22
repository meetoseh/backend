from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import NoReturn, Optional, List, Literal
from auth import auth_any
from daily_events.lib.has_started_one import has_started_one
from daily_events.lib.read_one_external import read_one_external
from itgs import Itgs
from models import StandardErrorResponse, STANDARD_ERRORS_BY_CODE
from daily_events.models.external_daily_event import ExternalDailyEvent
from users.lib.entitlements import get_entitlement
import perpetual_pub_sub as pps
from daily_events.auth import create_jwt
import time


router = APIRouter()


ERROR_404_TYPES = Literal["not_found"]
ERROR_503_TYPES = Literal["integrity_error"]


@router.get(
    "/now",
    response_model=ExternalDailyEvent,
    responses={
        "404": {
            "description": "There is no daily event available right now",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def get_current_daily_event(authorization: Optional[str] = Header(None)):
    """Provides a description of the current daily event and the jwt to use to
    access it. This JWT is generally single-use and short-lived.

    Note that you can call this endpoint multiple times before consuming earlier
    JWTs, but in that case, you may have fewer permissions available than indicated
    by both the response and the JWT. For example, if you call this two get two jwt's
    both with permission to start a random journey, and you consume the second one,
    the first may no longer work. Hence, these JWTs in particular should be thought of
    as an implementation detail more than reducing network traffic.

    This requires standard authorization, and will check entitlements and return
    a JWT with the appropriate access, which is described in the response.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        now = time.time()
        current_daily_event_uid = await get_current_daily_event_uid(itgs, now=now)
        if current_daily_event_uid is None:
            return Response(
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="not_found",
                    message="There is no daily event available right now",
                ).json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=404,
            )

        pro = await get_entitlement(
            itgs, user_sub=auth_result.result.sub, identifier="pro"
        )
        if pro.is_active:
            res = await read_one_external(
                itgs, uid=current_daily_event_uid, level={"read", "start_full"}
            )
            if res is None:
                return await _integrity_error(itgs)
            return res

        started_one = await has_started_one(
            itgs,
            user_sub=auth_result.result.sub,
            daily_event_uid=current_daily_event_uid,
        )
        level = {"read", "start_none" if started_one else "start_random"}

        res = await read_one_external(itgs, uid=current_daily_event_uid, level=level)
        if res is None:
            return await _integrity_error(itgs)

        return res


async def _integrity_error(itgs: Itgs) -> Response:
    await evict_current_daily_event(itgs)
    return Response(
        content=StandardErrorResponse[ERROR_503_TYPES](
            type="integrity_error",
            message="The current daily event is not available, try again",
        ).json(),
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Retry-After": "1",
        },
        status_code=503,
    )


async def get_current_daily_event_uid(itgs: Itgs, *, now: float) -> Optional[str]:
    """Gets the uid of the currently available daily event. This will fetch
    the uid from the local cache, if available, before falling back to the
    database.

    Args:
        itgs (Itgs): The integrations to (re)use
        now (float): The current time, in seconds since the epoch

    Returns:
        str, None: The uid of the current daily event, if there is a daily
            event available right now, otherwise None
    """
    local_cache = await itgs.local_cache()
    daily_event_uid = local_cache.get(b"daily_events:current")
    if daily_event_uid is not None:
        return str(daily_event_uid, "utf-8")

    conn = await itgs.conn()
    cursor = conn.cursor("strong")
    response = await cursor.execute(
        """
        SELECT
            uid, available_at
        FROM daily_events
        WHERE
            available_at <= ?
        ORDER BY available_at DESC, uid ASC
        LIMIT 2
        """,
        (now,),
    )

    if not response.results:
        return None

    daily_event_uid: str = response.results[0][0]
    next_daily_event_available_at: Optional[float] = (
        response.results[1][1] if len(response.results) > 1 else None
    )

    expires_in = (
        next_daily_event_available_at - now
        if next_daily_event_available_at is not None
        else 60 * 60 * 24
    )

    local_cache.set(
        b"daily_events:current",
        daily_event_uid.encode("utf-8"),
        expire=expires_in,
        tag="collab",
    )
    return daily_event_uid


async def evict_current_daily_event(itgs: Itgs) -> None:
    """Evicts all instances locally cached current daily event uids. This
    should be called whenever the current daily event changes (besides due
    to time), or when the next daily event starts changes.

    Args:
        itgs (Itgs): The integrations to (re)use
    """
    message = DailyEventsNowPurgeCachePubSubMessage(min_checked_at=time.time())

    redis = await itgs.redis()
    await redis.publish(
        b"ps:daily_events:now:purge_cache", message.json().encode("utf-8")
    )


class DailyEventsNowPurgeCachePubSubMessage(BaseModel):
    min_checked_at: float = Field()


async def purge_loop() -> NoReturn:
    """Infinitely loops, listening for messages to purge the local cache of
    current daily event uids. This should only be called once by the main thread.
    """
    async with pps.PPSSubscription(
        pps.instance, "ps:daily_events:now:purge_cache", "de_now"
    ) as sub:
        async for _ in sub:
            async with Itgs() as itgs:
                local_cache = await itgs.local_cache()
                local_cache.delete("daily_events:current")
