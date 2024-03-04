import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from typing import Annotated, Optional
from models import STANDARD_ERRORS_BY_CODE
from auth import auth_any
from itgs import Itgs
from redis_helpers.stripe_queue_or_lock_sync import stripe_queue_or_lock_sync_safe
from loguru import logger
import lib.shared.sync_user_stripe_revenue_cat

router = APIRouter()


@router.post(
    "/stripe/sync",
    status_code=200,
    responses={
        202: {
            "description": "The request was queued instead of processed immediately."
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def sync_stripe(authorization: Annotated[Optional[str], Header()] = None):
    """Requests that we double check the subscriptions of the authorized user on
    stripe. This is ratelimited to prevent abuse, but to keep it simple, if this
    is requested during the ratelimiting period it will cause the sync to occur
    as soon as the ratelimiting period ends. In other words, regardless of the
    result, the users stripe subscriptions will be double checked as soon as
    possible after the request is made.

    Requires standard authorization.
    """
    request_at = time.time()

    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        logger.debug(
            f"Handling request to sync revenue_cat<->stripe for {auth_result.result.sub}"
        )
        result = await stripe_queue_or_lock_sync_safe(
            itgs, user_sub=auth_result.result.sub.encode("utf-8"), now=int(request_at)
        )

        if result != "locked":
            logger.debug(
                f"Ratelimiting sync request for {auth_result.result.sub} was {result}"
            )
            return Response(status_code=202)

        logger.info(
            f"Ratelimiting revenue_cat<->stripe sync request for {auth_result.result.sub} was {result}"
        )
        await lib.shared.sync_user_stripe_revenue_cat.sync_user_stripe_revenue_cat(
            itgs, user_sub=auth_result.result.sub
        )
        return Response(status_code=200)
