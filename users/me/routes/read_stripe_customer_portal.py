import asyncio
import os
import secrets
import socket
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Annotated, Any, Dict, Literal, Optional, cast
from auth import auth_any
from error_middleware import handle_warning
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from starlette.concurrency import run_in_threadpool
import stripe
from itgs import Itgs
from redis_helpers.stripe_del_customer_portal_if_held import (
    stripe_del_customer_portal_if_held_safe,
)
from redis_helpers.stripe_lock_or_retrieve_customer_portal import (
    StripeCustomerPortalState,
    StripeCustomerPortalStateAvailable,
    StripeCustomerPortalStateUnavailable,
    StripeLockOrRetrieveCustomerPortalResultFailed,
    stripe_lock_or_retrieve_customer_portal_safe,
    stripe_customer_portal_state_adapter,
)
from loguru import logger


router = APIRouter()


class ReadStripeCustomerPortalRequest(BaseModel):
    return_path: Literal["/settings/manage-membership?sync=1"] = Field(
        description="The path to redirect the user to after they have finished with the customer portal."
    )


class ReadStripeCustomerPortalResponse(BaseModel):
    url: str = Field(description="The URL to redirect the user to the customer portal.")


ERROR_404_TYPES = Literal["not_found"]
ERROR_NOT_FOUND_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="not_found",
        message="The user does not have a need for a stripe customer portal.",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=404,
)

ERROR_429_TYPES = Literal["ratelimited"]
ERROR_RATELIMITED_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_429_TYPES](
        type="ratelimited",
        message="You must wait before trying again.",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8", "Retry-After": "60"},
    status_code=429,
)

ERROR_503_TYPES = Literal["multiple_stripe_users"]
ERROR_MULTIPLE_STRIPE_USERS_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_503_TYPES](
        type="multiple_stripe_users",
        message="The user has multiple associated stripe customers, and its not clear which one to return",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=503,
)

LONG_POLL_TIMEOUT = 5


@router.post(
    "/stripe/customer_portal",
    response_model=ReadStripeCustomerPortalResponse,
    responses={
        "404": {
            "description": "The user does not have a need for a stripe customer portal.",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        "429": {
            "description": "The user has exceeded the rate limit for this endpoint.",
            "model": StandardErrorResponse[ERROR_429_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def read_stripe_customer_portal(
    args: ReadStripeCustomerPortalRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Fetches the appropriate stripe customer portal URL for the authorized user.
    This will fail if the user is not subscribed via stripe, since it would not make
    sense to redirect them to the customer portal in that case.

    Generally the result is cached for a brief period and hence it does not make
    sense to limit calls to this endpoint, however, concurrent requests may be
    blocked and in the event of errors, backoff may be enforced. To make the
    endpoint convienent to use, most scenarios where retries would be necessary
    are hidden via long-polling.

    Requires standard authorization.
    """
    request_at = time.time()
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        str_request_id = secrets.token_urlsafe(16)
        request_id = str_request_id.encode("utf-8")
        redis_key = f"stripe:customer_portals:{auth_result.result.sub}".encode("utf-8")
        pubsub_redis_key = (
            f"ps:stripe:customer_portals:{auth_result.result.sub}".encode("utf-8")
        )
        logger.debug(
            f"Acquiring lock {request_id} or reading customer portal URL for {auth_result.result.sub} via {redis_key}"
        )

        lock_result = await stripe_lock_or_retrieve_customer_portal_safe(
            itgs,
            redis_key,
            socket.gethostname().encode("utf-8"),
            int(request_at),
            request_id,
        )

        if lock_result.success is False and lock_result.current_value.type == "loading":
            logger.debug(
                f"Detected contention getting lock {request_id} for customer portal URL for {auth_result.result.sub}, "
                f"trying long-polling up to {LONG_POLL_TIMEOUT}s"
            )
            redis = await itgs.redis()
            pubsub = redis.pubsub()
            await pubsub.subscribe(pubsub_redis_key)
            logger.debug(
                f"Subscribed to {pubsub_redis_key} for long-polling customer portal URL for {auth_result.result.sub}, "
                "checking if the value was set while we were waiting"
            )
            lock_result = await stripe_lock_or_retrieve_customer_portal_safe(
                itgs,
                redis_key,
                socket.gethostname().encode("utf-8"),
                int(request_at),
                request_id,
            )
            if (
                lock_result.success is not False
                or lock_result.current_value.type != "loading"
            ):
                logger.debug(
                    "Lock result changed while we were waiting, canceling subscription and processing"
                )
                await pubsub.unsubscribe(pubsub_redis_key)
                await pubsub.aclose()
            else:
                logger.debug(
                    f"Lock is still held, lingering for up to {LONG_POLL_TIMEOUT}s for a message from "
                    f"{pubsub_redis_key} for customer portal URL for {auth_result.result.sub}"
                )
                timeout_at = time.time() + LONG_POLL_TIMEOUT
                message: Optional[Dict[str, Any]] = None
                while True:
                    remaining_time = timeout_at - time.time()
                    if remaining_time <= 0.2:
                        break
                    message = await pubsub.get_message(timeout=remaining_time)
                    if message is not None:
                        if message["type"] == "message":
                            break
                        logger.debug(
                            f"Ignoring non-message from {pubsub_redis_key}: {message!r}"
                        )

                # Don't log the message directly; it contains the URL
                logger.debug(
                    f"Message from {pubsub_redis_key} for customer portal URL for {auth_result.result.sub} received"
                )
                await pubsub.unsubscribe(pubsub_redis_key)
                await pubsub.aclose()

                if message is not None and message["type"] == "message":
                    message_value = cast(
                        StripeCustomerPortalState,
                        stripe_customer_portal_state_adapter.validate_json(
                            message["data"]
                        ),
                    )
                    lock_result = StripeLockOrRetrieveCustomerPortalResultFailed(
                        success=False,
                        current_value=message_value,
                    )

        if lock_result.success is False:
            if lock_result.current_value.type == "loading":
                logger.warning(
                    f"Failed to acquire customer portal URL for {auth_result.result.sub} as its already being "
                    f"fetched: {lock_result.current_value!r}"
                )
                return ERROR_RATELIMITED_RESPONSE
            if lock_result.current_value.type == "unavailable":
                if lock_result.current_value.reason == "no-customer":
                    logger.warning(
                        f"Failed to acquire customer portal URL for {auth_result.result.sub} via "
                        f"cached information that they do not need a customer portal, which was "
                        f"checked at {lock_result.current_value.checked_at}"
                    )
                    return ERROR_NOT_FOUND_RESPONSE
                if lock_result.current_value.reason == "multiple-customers":
                    logger.warning(
                        f"Failed to acquire customer portal URL for {auth_result.result.sub} via "
                        f"cached information that they dhave multiple relevant stripe customers, which was "
                        f"checked at {lock_result.current_value.checked_at}"
                    )
                    return ERROR_MULTIPLE_STRIPE_USERS_RESPONSE
                raise ValueError(
                    f"Unexpected lock result: {lock_result.current_value!r}"
                )
            if lock_result.current_value.type == "available":
                logger.info(
                    f"Returning cached customer portal URL for {auth_result.result.sub}"
                )
                return Response(
                    content=ReadStripeCustomerPortalResponse(
                        url=lock_result.current_value.url
                    ).model_dump_json(),
                    headers={"Content-Type": "application/json; charset=utf-8"},
                    status_code=200,
                )
            raise ValueError(f"Unexpected lock result: {lock_result.current_value!r}")

        assert lock_result.success is True, lock_result
        logger.debug(
            f"Acquired lock {request_id} to read customer portal URL for {auth_result.result.sub}; fetching customer ids"
        )
        redis = await itgs.redis()

        try:
            conn = await itgs.conn()
            cursor = conn.cursor("weak")

            response = await cursor.execute(
                "SELECT"
                " stripe_customers.stripe_customer_id "
                "FROM users, stripe_customers "
                "WHERE"
                " users.sub = ? AND stripe_customers.user_id = users.id "
                "ORDER BY stripe_customers.created_at DESC, stripe_customers.uid ASC",
                (auth_result.result.sub,),
            )
            if not response.results:
                logger.warning(
                    f"Customer Portal URL {request_id} for {auth_result.result.sub} failed to find any stripe customers"
                )
                new_value = StripeCustomerPortalStateUnavailable(
                    type="unavailable",
                    reason="no-customer",
                    checked_at=int(request_at),
                )
            else:
                stripe_customer_ids = [cast(str, row[0]) for row in response.results]
                logger.debug(
                    f"Customer Portal URL {request_id} for {auth_result.result.sub} checking stripe customers: {stripe_customer_ids}..."
                )

                stripe_sk = os.environ["OSEH_STRIPE_SECRET_KEY"]
                stripe_customers = await asyncio.wait_for(
                    asyncio.gather(
                        *[
                            run_in_threadpool(
                                stripe.Customer.retrieve,
                                customer_id,
                                api_key=stripe_sk,
                                expand=["subscriptions"],
                            )
                            for customer_id in stripe_customer_ids
                        ]
                    ),
                    timeout=60,
                )
                logger.debug(
                    f"Customer Portal URL {request_id} for {auth_result.result.sub} found {len(stripe_customers)} customers..."
                )

                relevant_stripe_customers = [
                    customer
                    for customer in stripe_customers
                    if customer.subscriptions is not None
                    and customer.subscriptions.data
                ]
                if len(relevant_stripe_customers) == 0:
                    logger.warning(
                        f"Customer Portal URL {request_id} for {auth_result.result.sub} found no relevant stripe customers"
                    )
                    new_value = StripeCustomerPortalStateUnavailable(
                        type="unavailable",
                        reason="no-customer",
                        checked_at=int(request_at),
                    )
                elif len(relevant_stripe_customers) == 1:
                    customer_for_portal = relevant_stripe_customers[0]
                    logger.info(
                        f"Customer Portal URL {request_id} for {auth_result.result.sub} "
                        f"found stripe customer for customer portal: {customer_for_portal.id}"
                    )
                    billing_portal_session = await asyncio.wait_for(
                        run_in_threadpool(
                            stripe.billing_portal.Session.create,
                            customer=customer_for_portal.id,
                            api_key=stripe_sk,
                            return_url=(
                                os.environ["ROOT_FRONTEND_URL"] + args.return_path
                            ),
                        ),
                        timeout=60,
                    )
                    logger.info(
                        f"Customer Portal URL {request_id} for {auth_result.result.sub} "
                        "generated a billing portal session"
                    )
                    new_value = StripeCustomerPortalStateAvailable(
                        type="available",
                        url=billing_portal_session.url,
                        checked_at=int(request_at),
                    )
                else:
                    logger.warning(
                        f"Customer Portal URL {request_id} for {auth_result.result.sub} found multiple relevant stripe customers"
                    )
                    new_value = StripeCustomerPortalStateUnavailable(
                        type="unavailable",
                        reason="multiple-customers",
                        checked_at=int(request_at),
                    )

            serd_new_value = new_value.__pydantic_serializer__.to_json(new_value)
            async with redis.pipeline() as pipe:
                pipe.multi()
                await pipe.get(redis_key)
                await pipe.set(
                    redis_key,
                    serd_new_value,
                    ex=60,
                )
                await pipe.publish(
                    pubsub_redis_key,
                    serd_new_value,
                )
                res = await pipe.execute()

            old_value: Optional[bytes] = res[0]
            if old_value is None:
                await handle_warning(
                    f"{__name__}:lock_lost",
                    f"While retrieving customer portal URL for {auth_result.result.sub}, the lock expired. "
                    "No other instances tried to acquire the URL in the meantime (or they also already expired), "
                    "so this is not dangerous, but it does indicate we may need to adjust the lock timeout.",
                )
            else:
                parsed_old_value = cast(
                    StripeCustomerPortalState,
                    stripe_customer_portal_state_adapter.validate_json(old_value),
                )
                if (
                    parsed_old_value.type != "loading"
                    or parsed_old_value.id != str_request_id
                ):
                    await handle_warning(
                        f"{__name__}:lock_ripped",
                        f"While retrieving customer portal URL for {auth_result.result.sub}, another instance "
                        "changed our locked key. If the implementation is correct, this means our lock "
                        "expired and another request came in. We may need to adjust the lock timeout.\n\n"
                        f"```\nrequest_id: {str_request_id!r}\nold_value: {parsed_old_value!r}\nnew_value: {new_value!r}\n```",
                    )

            if new_value.type == "unavailable":
                if new_value.reason == "no-customer":
                    return ERROR_NOT_FOUND_RESPONSE
                if new_value.reason == "multiple-customers":
                    return ERROR_MULTIPLE_STRIPE_USERS_RESPONSE
                raise ValueError(f"Unexpected new value: {new_value!r}")
            if new_value.type == "available":
                return Response(
                    content=ReadStripeCustomerPortalResponse(
                        url=new_value.url
                    ).model_dump_json(),
                    headers={"Content-Type": "application/json; charset=utf-8"},
                    status_code=200,
                )
            raise ValueError(f"Unexpected new value: {new_value!r}")
        except Exception as e:
            logger.error(
                f"Customer Portal URL {request_id} for {auth_result.result.sub} failed: {e!r}"
            )
            res = await stripe_del_customer_portal_if_held_safe(
                itgs, redis_key, request_id
            )
            if res.type != "success":
                await handle_warning(
                    f"{__name__}:exceptional_release_failed",
                    f"Lost customer portal lock for {auth_result.result.sub} after exceptional failure:\n\n```\n{res!r}\n```\n",
                    exc=e,
                )
            raise
