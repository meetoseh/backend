import json
import secrets
import time
from fastapi import APIRouter, Request, Header
from fastapi.responses import Response
from lib.client_flows.client_screen_stats_preparer import ClientScreenStatsPreparer
from lib.redis_stats_preparer import redis_stats
from models import STANDARD_ERRORS_BY_CODE
from typing import Annotated, Optional
from users.me.screens.auth import auth_any
from itgs import Itgs
import unix_dates
import pytz

from visitors.lib.get_or_create_visitor import VisitorSource


router = APIRouter()

tz = pytz.timezone("America/Los_Angeles")


@router.post(
    "/trace",
    status_code=204,
    responses={
        "400": {"description": "The request body was not valid json"},
        "413": {"description": "The request body was 2048 bytes or more"},
        "415": {
            "description": "The content-type header was not `application/json; charset=utf-8`"
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def trace_screen(
    req: Request,
    platform: VisitorSource,
    version: Optional[int] = None,
    authorization: Annotated[Optional[str], Header()] = None,
    content_type: Annotated[Optional[str], Header(include_in_schema=False)] = None,
):
    """Associates an event with the given screen, primarily for debugging
    purposes. This may not actually be stored.

    This event anticipates that client may want to defer tracing for performance
    reasons, and thus you can store events after a screen has already been popped
    off but before the JWT expires. This means, for example, if you want to trace
    an event "right before" popping, since popping is more urgent you can defer
    the final trace until a better moment.

    This returns failure status codes for requests that will never result in an
    event being stored to assist debugging, but requests should never be retried
    or presented to users in production.

    The content-type header must EXACTLY be `application/json; charset=utf-8`

    The request body must be valid json and less than 2048 bytes.

    Requires authorization for the client screen to associate the event with.
    """
    if content_type != "application/json; charset=utf-8":
        return Response(status_code=415)

    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        body = await req.body()
        if len(body) > 2048:
            return Response(status_code=413)

        # we need to decode before storing anyway, which could in theory
        # speed up the json validation step
        try:
            str_body = body.decode("utf-8")
        except:
            return Response(status_code=400)

        # PERF: probably spends most of its time allocating since PyObjects are huge.
        # might be better to use sqlite3's json() instead, via e.g. the diskcache
        # sqlite3 connection which is already available, which is at least way faster
        try:
            json.loads(str_body)
        except:
            return Response(status_code=400)

        conn = await itgs.conn()
        cursor = conn.cursor()
        now = time.time()
        await cursor.execute(
            """
INSERT INTO user_client_screen_actions_log (
    uid, user_client_screen_log_id, event, created_at
)
SELECT
    ?, user_client_screens_log.id, ?, ?
FROM user_client_screens_log
WHERE
    user_client_screens_log.uid = ?
            """,
            (
                f"oseh_ucsal_{secrets.token_urlsafe(16)}",
                str_body,
                now,
                auth_result.result.user_client_screen_log_uid,
            ),
        )

        unix_date = unix_dates.unix_timestamp_to_unix_date(now, tz=tz)
        async with redis_stats(itgs) as stats:
            ClientScreenStatsPreparer(stats).incr_traced(
                unix_date=unix_date,
                platform=platform,
                version=version,
                slug=auth_result.result.screen_slug,
            )

        return Response(status_code=204)
