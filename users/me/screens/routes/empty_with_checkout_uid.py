import os
import time
from fastapi import APIRouter, Header
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
import stripe
from error_middleware import handle_contextless_error, handle_error
from lib.client_flows.executor import (
    ClientScreenQueuePeekInfo,
    TrustedTrigger,
    execute_peek,
)
from lib.shared.describe_user import enqueue_send_described_user_slack_message
from models import (
    AUTHORIZATION_UNKNOWN_TOKEN,
    STANDARD_ERRORS_BY_CODE,
)
from typing import Annotated, Optional, cast
from itgs import Itgs
import auth as std_auth
from users.me.routes.finish_checkout_stripe import FinishCheckoutStripeRequest

from users.me.screens.lib.realize_screens import realize_screens
from users.me.screens.models.peeked_screen import PeekScreenResponse
from visitors.lib.get_or_create_visitor import VisitorSource

import users.lib.revenue_cat
import users.lib.entitlements as entitlements


router = APIRouter()


@router.post(
    "/empty_with_checkout_uid",
    response_model=PeekScreenResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def empty_with_checkout_uid(
    args: FinishCheckoutStripeRequest,
    platform: VisitorSource,
    visitor: Annotated[Optional[str], Header()] = None,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """A specialized endpoint which is intended to be used when redirected back
    from stripe with a checkout uid in the query string. Since you were
    redirected back, you don't have a screen peeked yet, so a screen JWT is not
    required. Instead, this always triggers the same flow
    (`post_checkout_success`) if they have oseh+ and `post_checkout_failure` if
    they don't.

    These flows usually have `replaces=True`, hence the name `empty` in the api
    path, but that isn't _necessarily_ the case.

    For the app, busting the entitlement cache and then using a regular pop is
    sufficient, i.e., no custom pop endpoint is provided.

    Requires standard authorization for a user.
    """
    request_at = time.time()
    async with Itgs() as itgs:
        std_auth_result = await std_auth.auth_any(itgs, authorization)
        if std_auth_result.result is None:
            return std_auth_result.error_response

        user_sub = std_auth_result.result.sub

        async def _realize(screen: ClientScreenQueuePeekInfo):
            result = await realize_screens(
                itgs,
                user_sub=user_sub,
                platform=platform,
                visitor=visitor,
                result=screen,
            )

            return Response(
                content=result.__pydantic_serializer__.to_json(result),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=200,
            )

        redis = await itgs.redis()
        ratelimit_success = await redis.set(
            f"checkout:stripe:finish:ratelimit:{std_auth_result.result.sub}",
            1,
            ex=15,
            nx=True,
        )
        if not ratelimit_success:
            await handle_contextless_error(
                extra_info=f"user {std_auth_result.result.sub} attempted to finish a checkout session {args.checkout_uid}; due to excessive requests, we ignored it"
            )
            screen = await execute_peek(
                itgs,
                user_sub=std_auth_result.result.sub,
                platform=platform,
                trigger=None,
            )
            return await _realize(screen)

        conn = await itgs.conn()
        cursor = conn.cursor("weak")

        response = await cursor.execute(
            """
            SELECT
                open_stripe_checkout_sessions.stripe_checkout_session_id
            FROM open_stripe_checkout_sessions
            WHERE
                open_stripe_checkout_sessions.uid = ?
                AND EXISTS (
                    SELECT 1 FROM users
                    WHERE open_stripe_checkout_sessions.user_id = users.id
                      AND users.sub = ?
                )
            """,
            (args.checkout_uid, std_auth_result.result.sub),
        )
        if not response.results:
            await handle_contextless_error(
                extra_info=f"user {std_auth_result.result.sub} attempted to finish a checkout session {args.checkout_uid} which we don't know about"
            )
            screen = await execute_peek(
                itgs,
                user_sub=std_auth_result.result.sub,
                platform=platform,
                trigger=None,
            )
            return await _realize(screen)

        stripe_checkout_session_id = cast(str, response.results[0][0])

        try:
            checkout_session = await run_in_threadpool(
                stripe.checkout.Session.retrieve,
                stripe_checkout_session_id,
                api_key=os.environ["OSEH_STRIPE_SECRET_KEY"],
            )
        except Exception as exc:
            await handle_error(exc)
            screen = await execute_peek(
                itgs,
                user_sub=std_auth_result.result.sub,
                platform=platform,
                trigger=None,
            )
            return await _realize(screen)

        if checkout_session.status != "complete":
            await handle_contextless_error(
                extra_info=f"user {std_auth_result.result.sub} attempted to finish a checkout session {args.checkout_uid} which is not complete"
            )
            await cursor.execute(
                """
                UPDATE open_stripe_checkout_sessions
                SET last_checked_at=?
                WHERE uid=?
                """,
                (request_at, args.checkout_uid),
            )
            screen = await execute_peek(
                itgs,
                user_sub=std_auth_result.result.sub,
                platform=platform,
                trigger=None,
            )
            return await _realize(screen)

        if (
            checkout_session.amount_total is not None
            and checkout_session.amount_total > 0
        ):
            await enqueue_send_described_user_slack_message(
                itgs,
                message=f"{{name}} just finalized a checkout session for ${checkout_session.amount_total / 100:.2f}! 🎉",
                sub=std_auth_result.result.sub,
                channel="oseh_bot",
            )

        try:
            revenue_cat_id = (
                await users.lib.revenue_cat.get_or_create_latest_revenue_cat_id(
                    itgs, user_sub=std_auth_result.result.sub, now=request_at
                )
            )
        except Exception as exc:
            await handle_error(
                exc,
                extra_info=f"{std_auth_result.result.sub=}, {args.checkout_uid=}, {checkout_session.id=}",
            )
            screen = await execute_peek(
                itgs,
                user_sub=std_auth_result.result.sub,
                platform=platform,
                trigger=None,
            )
            return await _realize(screen)

        if revenue_cat_id is None:
            return AUTHORIZATION_UNKNOWN_TOKEN

        rc = await itgs.revenue_cat()
        try:
            await rc.create_stripe_purchase(
                revenue_cat_id=revenue_cat_id,
                stripe_checkout_session_id=stripe_checkout_session_id,
            )
        except Exception as exc:
            await handle_error(
                exc,
                extra_info=f"{std_auth_result.result.sub=}, {args.checkout_uid=}, {revenue_cat_id=}, {stripe_checkout_session_id=}",
            )
            screen = await execute_peek(
                itgs,
                user_sub=std_auth_result.result.sub,
                platform=platform,
                trigger=None,
            )
            return await _realize(screen)

        await cursor.execute(
            "DELETE FROM open_stripe_checkout_sessions WHERE uid=?",
            (args.checkout_uid,),
        )
        pro_entitlement = await entitlements.get_entitlement(
            itgs,
            user_sub=std_auth_result.result.sub,
            identifier="pro",
            force=True,
        )
        screen = await execute_peek(
            itgs,
            user_sub=std_auth_result.result.sub,
            platform=platform,
            trigger=TrustedTrigger(
                flow_slug=(
                    "post_checkout_success"
                    if pro_entitlement is not None and pro_entitlement.is_active
                    else "post_checkout_failure"
                ),
                client_parameters={},
                server_parameters={},
            ),
        )
        return await _realize(screen)
