import json
import os
from fastapi import FastAPI, Request
from fastapi.responses import Response
from starlette.middleware.cors import CORSMiddleware
from error_middleware import handle_request_error, handle_error
from itgs import Itgs, our_diskcache
from lifespan import (
    first_lifespan_handler,
    top_level_lifespan_handler,
)
from mp_helper import adapt_threading_event_to_asyncio
import perpetual_pub_sub
import secrets
import updater
import users.lib.entitlements
import migrations.main
import continuous_deployment.router
import users.router
import image_files.router
import journeys.router
import file_uploads.router
import content_files.router
import instructors.router
import oauth.router
import admin.router
import dev.router
import phones.router
import notifications.router
import interactive_prompts.router
import visitors.router
import vip_chat_requests.router
import courses.router
import emotions.router
import personalization.router
import campaigns.router
import interests.router
import sms.router
import emails.router
import misc.router
import onboarding.router
import touch_points.router
import personalization.register_background_tasks
import admin.routes.read_journey_subcategory_view_stats
import journeys.lib.read_one_external
import interactive_prompts.routes.profile_pictures
import interactive_prompts.lib.read_one_external
import interactive_prompts.lib.read_interactive_prompt_meta
import admin.notifs.routes.read_daily_push_tokens
import admin.notifs.routes.read_daily_push_tickets
import admin.notifs.routes.read_daily_push_receipts
import admin.sms.routes.read_daily_sms_sends
import admin.sms.routes.read_daily_sms_polling
import admin.sms.routes.read_daily_sms_events
import transcripts.router
import client_screens.router
import client_flows.router
import asyncio
from loguru import logger
from typing import cast as typing_cast


if (
    os.environ.get("ENVIRONMENT") != "production"
    and os.environ.get("OSEH_STRIPE_SECRET_KEY") not in (None, "")
    and not os.environ["OSEH_STRIPE_SECRET_KEY"].startswith("sk_test_")
):
    exc = Exception(
        "OSEH_STRIPE_SECRET_KEY is not a test key, but we are not "
        "in production. did you forget to set ENVIRONMENT?"
    )
    asyncio.run(handle_error(exc))
    raise exc


# Collaboratively locally cached items are items which we cache on this
# instance, but our cache time relies on other instances informing us
# about updates. If we were just restarted, we may have missed updates,
# and hence need to evict our cache and pull from source next time.
while our_diskcache.evict(tag="collab") > 0:
    ...


@first_lifespan_handler
async def register_background_tasks():
    if perpetual_pub_sub.instance is None:
        perpetual_pub_sub.instance = perpetual_pub_sub.PerpetualPubSub()

    logger.add(typing_cast(str, "backend.log"), enqueue=True, rotation="100 MB")

    background_tasks = set()
    background_tasks.add(
        asyncio.create_task(perpetual_pub_sub.instance.run_in_background_async())
    )
    background_tasks.add(asyncio.create_task(updater.listen_forever()))
    background_tasks.add(asyncio.create_task(migrations.main.main()))
    background_tasks.add(
        asyncio.create_task(users.lib.entitlements.purge_cache_loop_async())
    )
    background_tasks.add(
        asyncio.create_task(
            admin.routes.read_journey_subcategory_view_stats.listen_available_responses_forever()
        )
    )
    background_tasks.add(
        asyncio.create_task(journeys.lib.read_one_external.cache_push_loop())
    )
    background_tasks.add(
        asyncio.create_task(
            interactive_prompts.routes.profile_pictures.cache_push_loop()
        )
    )
    background_tasks.add(
        asyncio.create_task(interactive_prompts.lib.read_one_external.cache_push_loop())
    )
    background_tasks.add(
        asyncio.create_task(
            interactive_prompts.lib.read_interactive_prompt_meta.cache_push_loop()
        )
    )
    personalization.register_background_tasks.register_background_tasks(
        background_tasks
    )
    background_tasks.add(
        asyncio.create_task(
            admin.notifs.routes.read_daily_push_tokens.handle_reading_daily_push_tokens_from_other_instances()
        )
    )
    background_tasks.add(
        asyncio.create_task(
            admin.notifs.routes.read_daily_push_tickets.handle_reading_daily_push_tickets_from_other_instances()
        )
    )
    background_tasks.add(
        asyncio.create_task(
            admin.notifs.routes.read_daily_push_receipts.handle_reading_daily_push_receipts_from_other_instances()
        )
    )
    background_tasks.add(
        asyncio.create_task(
            admin.sms.routes.read_daily_sms_sends.handle_reading_daily_sms_sends_from_other_instances()
        )
    )
    background_tasks.add(
        asyncio.create_task(
            admin.sms.routes.read_daily_sms_polling.handle_reading_daily_sms_polling_from_other_instances()
        )
    )
    background_tasks.add(
        asyncio.create_task(
            admin.sms.routes.read_daily_sms_events.handle_reading_daily_sms_events_from_other_instances()
        )
    )
    yield
    perpetual_pub_sub.instance.exit_event.set()

    await adapt_threading_event_to_asyncio(
        perpetual_pub_sub.instance.exitted_event
    ).wait()


app = FastAPI(
    title="oseh",
    description="hypersocial daily mindfulness",
    version="1.0.0+alpha",
    openapi_url="/api/1/openapi.json",
    docs_url="/api/1/docs",
    exception_handlers={Exception: handle_request_error},
    lifespan=top_level_lifespan_handler,
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info(f"Request Starting: {request.method} {request.url}")
    response = await call_next(request)
    logger.info(f"Request Finished: {request.url}")
    return response


if os.environ.get("ENVIRONMENT") == "dev":
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[os.environ["ROOT_FRONTEND_URL"]],
        allow_credentials=True,
        allow_methods=["GET", "POST", "HEAD", "PUT", "DELETE", "PATCH"],
        allow_headers=["Authorization", "Pragma", "Cache-Control", "Visitor"],
        expose_headers=["x-image-file-jwt"],
    )
app.include_router(
    continuous_deployment.router.router,
    prefix="/api/1/continuous_deployment",
    tags=["continuous_deployment"],
)
app.include_router(users.router.router, prefix="/api/1/users", tags=["users"])
app.include_router(
    image_files.router.router, prefix="/api/1/image_files", tags=["image_files"]
)
app.include_router(journeys.router.router, prefix="/api/1/journeys", tags=["journeys"])
app.include_router(
    file_uploads.router.router, prefix="/api/1/file_uploads", tags=["file_uploads"]
)
app.include_router(
    content_files.router.router, prefix="/api/1/content_files", tags=["content_files"]
)
app.include_router(
    instructors.router.router, prefix="/api/1/instructors", tags=["instructors"]
)
app.include_router(oauth.router.router, prefix="/api/1/oauth", tags=["oauth"])
app.include_router(admin.router.router, prefix="/api/1/admin", tags=["admin"])
app.include_router(dev.router.router, prefix="/api/1/dev", tags=["dev"])
app.include_router(phones.router.router, prefix="/api/1/phones", tags=["phones"])
app.include_router(
    notifications.router.router, prefix="/api/1/notifications", tags=["notifications"]
)
app.include_router(
    interactive_prompts.router.router,
    prefix="/api/1/interactive_prompts",
    tags=["interactive_prompts"],
)
app.include_router(visitors.router.router, prefix="/api/1/visitors", tags=["visitors"])
app.include_router(
    vip_chat_requests.router.router,
    prefix="/api/1/vip_chat_requests",
    tags=["vip_chat_requests"],
)
app.include_router(courses.router.router, prefix="/api/1/courses", tags=["courses"])
app.include_router(emotions.router.router, prefix="/api/1/emotions", tags=["emotions"])
app.include_router(
    personalization.router.router,
    prefix="/api/1/personalization",
    tags=["personalization"],
)
app.include_router(
    campaigns.router.router, prefix="/api/1/campaigns", tags=["campaigns"]
)
app.include_router(
    interests.router.router, prefix="/api/1/interests", tags=["interests"]
)
app.include_router(sms.router.router, prefix="/api/1/sms", tags=["sms"])
app.include_router(emails.router.router, prefix="/api/1/emails", tags=["emails"])
app.include_router(
    transcripts.router.router, prefix="/api/1/transcripts", tags=["transcripts"]
)
app.include_router(misc.router.router, prefix="/api/1/misc", tags=["misc"])
app.include_router(
    onboarding.router.router, prefix="/api/1/onboarding", tags=["onboarding"]
)
app.include_router(
    touch_points.router.router, prefix="/api/1/touch_points", tags=["touch_points"]
)
app.include_router(
    client_screens.router.router,
    prefix="/api/1/client_screens",
    tags=["client_screens"],
)
app.include_router(
    client_flows.router.router, prefix="/api/1/client_flows", tags=["client_flows"]
)
app.router.redirect_slashes = False


@app.get("/api/1")
def root():
    return {"message": "Hello World"}


@app.get("/api/1/test/rqdb")
async def test_rqdb():
    """Checks if the rqlite cluster is responding normally (2xx response)"""
    async with Itgs() as itgs:
        conn = await itgs.conn()
        res = await conn.cursor("none").execute("SELECT 2")
        assert res.results
        if res.rowcount != 1:
            return Response(
                content=json.dumps({"message": f"invalid rowcount: {res.rowcount}"}),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=503,
            )
        if res.results[0] != [2]:
            return Response(
                content=json.dumps({"message": f"invalid row: {repr(res.results[0])}"}),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=503,
            )
        return Response(
            content=json.dumps({"message": "rqlite cluster responding normally"}),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=200,
        )


@app.get("/api/1/test/redis")
async def test_redis():
    """Checks if the redis cluster is responding normally (2xx response)"""
    async with Itgs() as itgs:
        redis = await itgs.redis()

        test_key = f"__test{secrets.token_urlsafe(8)}".encode("utf-8")
        test_val = secrets.token_urlsafe(8).encode("utf-8")
        if not await redis.set(test_key, test_val):
            return Response(
                content=json.dumps(
                    {"message": f"failed to set {test_key=} to {test_val=} (non-OK)"}
                ),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=503,
            )
        val = await redis.get(test_key)
        if val != test_val:
            return Response(
                content=json.dumps(
                    {
                        "message": f"expected {test_key=} to have {test_val=} but got {val=}"
                    }
                ),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=503,
            )
        if not await redis.delete(test_key):
            return Response(
                content=json.dumps(
                    {"message": f"failed to delete {test_key=} (non-OK)"}
                ),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=503,
            )
        return Response(
            content=json.dumps({"message": "redis cluster responding normally"}),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )


@app.get("/api/1/test/division")
async def test_division(dividend: int, divisor: int):
    """returns dividend/divisor - but gives an internal server error
    if divisor = 0; useful for testing error reporting
    """
    return Response(
        content=json.dumps({"quotient": dividend / divisor}),
        headers={"Content-Type": "application/json; charset=utf-8"},
        status_code=200,
    )
