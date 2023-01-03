import random
from fastapi import APIRouter, Header
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from typing import AsyncGenerator, Literal, Optional
from daily_events.models.external_daily_event import ExternalDailyEvent
from journeys.models.external_journey import ExternalJourney
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from daily_events.lib.has_started_one import has_started_one, on_started_one
import auth
import daily_events.auth
import journeys.auth
import daily_events.lib.read_one_external
import journeys.lib.read_one_external
from itgs import Itgs
import secrets
import random
import io


router = APIRouter()


class StartRandomJourneyRequest(BaseModel):
    uid: str = Field(
        description=(
            "The UID of the daily event to start a random journey within. Included "
            "to catch some simple mistakes, but must match the sub of the JWT."
        )
    )
    jwt: str = Field(
        description=(
            "The JWT which provides access to the daily event. Must have either "
            "start_random or start_full access, and if it has start_random, it must "
            "not already have been consumed by a different JWT. The JWT is revoked after "
            "a successful call."
        )
    )


ERROR_409_TYPES = Literal["already_started"]
ALREADY_STARTED_ONE = Response(
    status_code=409,
    content=StandardErrorResponse[ERROR_409_TYPES](
        type="already_started",
        message="The start_random permission has already been consumed by a different JWT",
    ).json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
)

ERROR_404_TYPES = Literal["not_found"]
NOT_FOUND = Response(
    status_code=404,
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="not_found",
        message=(
            "Although the JWT you provided is valid, no such daily event exists; "
            "this is either a server error or the daily event has been deleted."
        ),
    ).json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
)


@router.post(
    "/start_random",
    status_code=201,
    response_model=ExternalJourney,
    responses={
        "404": {
            "description": (
                "Although the JWT you provided is valid, no such daily event exists; "
                "this is either a server error or the daily event has been deleted."
            ),
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        "409": {
            "description": "The start_random permission has already been consumed by a different JWT",
            "model": StandardErrorResponse[ERROR_409_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def start_random_journey(
    args: StartRandomJourneyRequest, authorization: Optional[str] = Header(None)
):
    """Starts a random journey within the given daily event. This begins a new
    session within the journey, which should be used to post events (at minimum
    the join and leave events). The returned JWT can also be used for connecting
    to the live stream of temporally adjacent events, the standard HTTP endpoint
    for historical events, and the standard HTTP endpoint for journey statistics
    across time.

    This endpoint exchanges a daily event JWT for a journey JWT. The daily event
    JWT must have either the start_random or start_full permission, and if it
    has start_random, it must not already have been consumed by a different JWT.
    The daily event JWT is revoked after a successful call.

    This also requires standard authorization, which is used to determine which
    user to associate with the session.
    """
    async with Itgs() as itgs:
        std_auth_result = await auth.auth_any(itgs, authorization)
        if not std_auth_result.success:
            return std_auth_result.error_response

        de_auth_result = await daily_events.auth.auth_any(itgs, f"bearer {args.jwt}")
        if not de_auth_result.success:
            return de_auth_result.error_response

        if de_auth_result.result.daily_event_uid != args.uid:
            return auth.AUTHORIZATION_UNKNOWN_TOKEN

        if not any(
            perm in de_auth_result.result.level
            for perm in ("start_random", "start_full")
        ):
            return auth.AUTHORIZATION_UNKNOWN_TOKEN

        # we will check, optimistically insert, then check again
        # to minimize the odds we lock them out but fail to start
        # the journey
        if "start_full" not in de_auth_result.result.level and await has_started_one(
            itgs,
            user_sub=std_auth_result.result.sub,
            daily_event_uid=de_auth_result.result.daily_event_uid,
        ):
            return ALREADY_STARTED_ONE

        journey_uid = await select_journey(itgs, de_auth_result.result.daily_event_uid)
        if journey_uid is None:
            return NOT_FOUND

        # preparation
        session_uid = f"oseh_js_{secrets.token_urlsafe(16)}"
        jwt = await journeys.auth.create_jwt(itgs, journey_uid=journey_uid)

        # fetch info
        journey_response = await journeys.lib.read_one_external.read_one_external(
            itgs, journey_uid=journey_uid, session_uid=session_uid, jwt=jwt
        )
        if journey_response is None:
            return NOT_FOUND

        async def cleanup_journey_response():
            if isinstance(journey_response, StreamingResponse) and hasattr(
                journey_response.body_iterator, "aclose"
            ):
                await journey_response.body_iterator.aclose()  # noqa

        # optimistically insert session
        conn = await itgs.conn()
        cursor = conn.cursor("weak")
        response = await cursor.execute(
            """
            INSERT INTO journey_sessions (
                journey_id,
                user_id,
                uid
            )
            SELECT
                journeys.id,
                users.id,
                ?
            FROM journeys, users
            WHERE
                journeys.uid = ?
                AND users.sub = ?
            """,
            (
                session_uid,
                journey_uid,
                std_auth_result.result.sub,
            ),
        )
        if response.rows_affected is None or response.rows_affected < 1:
            await cleanup_journey_response()
            return NOT_FOUND

        # finally, concurrency-safe check
        if (
            "start_full" not in de_auth_result.result.level
            and not await on_started_one(
                itgs,
                user_sub=std_auth_result.result.sub,
                daily_event_uid=de_auth_result.result.daily_event_uid,
                force=False,
            )
        ):
            await cursor.execute(
                "DELETE FROM journey_sessions WHERE uid = ?",
                (session_uid,),
            )
            await cleanup_journey_response()
            return ALREADY_STARTED_ONE

        # revoke the daily event JWT to ensure the client is always refetching it,
        # which is what we want them to do to refresh access permissions (rather
        # than internally maintaining state)
        await daily_events.auth.revoke_auth(itgs, result=de_auth_result.result)
        return journey_response


async def select_journey(itgs: Itgs, daily_event_uid: str) -> Optional[str]:
    """Selects a random journey within the given daily event. Returns None if
    there is no daily event with that uid
    """
    # PERF: This usually doesn't require any networking but is pretty
    #   inefficient cpu-wise compared to a dedicated cache. We could
    #   reuse more of the information used here, but in order to allow
    #   for a dedicated cache later, we don't do that now.
    daily_event_raw = await daily_events.lib.read_one_external.read_one_external(
        itgs, uid=daily_event_uid, level=set(["read", "start_random"])
    )

    if daily_event_raw is None:
        return None

    daily_event_bytes = None
    if isinstance(daily_event_raw, StreamingResponse):
        writer = io.BytesIO()
        async for chunk in daily_event_raw.body_iterator:
            if isinstance(chunk, str):
                chunk = chunk.encode("utf-8")
            writer.write(chunk)
        daily_event_bytes = writer.getvalue()
    else:
        daily_event_bytes = daily_event_raw.body

    daily_event = ExternalDailyEvent.parse_raw(daily_event_bytes)
    journey = random.choice(daily_event.journeys)
    return journey.uid
