import os
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware
from error_middleware import handle_request_error, handle_error
from itgs import Itgs, our_diskcache
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
import admin.routes.read_journey_subcategory_view_stats
import journeys.lib.read_one_external
import interactive_prompts.routes.profile_pictures
import interactive_prompts.lib.read_one_external
import interactive_prompts.lib.read_interactive_prompt_meta
import asyncio
from loguru import logger


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

app = FastAPI(
    title="oseh",
    description="hypersocial daily mindfulness",
    version="1.0.0+alpha",
    openapi_url="/api/1/openapi.json",
    docs_url="/api/1/docs",
    exception_handlers={Exception: handle_request_error},
)

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
app.router.redirect_slashes = False


background_tasks = set()

if perpetual_pub_sub.instance is None:
    perpetual_pub_sub.instance = perpetual_pub_sub.PerpetualPubSub()


@app.on_event("startup")
def register_background_tasks():
    logger.add("backend.log", enqueue=True, rotation="100 MB")

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


@app.on_event("shutdown")
async def cleanly_shutdown_perpetual_pub_sub():
    perpetual_pub_sub.instance.exit_event.set()

    await adapt_threading_event_to_asyncio(
        perpetual_pub_sub.instance.exitted_event
    ).wait()


@app.get("/api/1")
def root():
    return {"message": "Hello World"}


@app.get("/api/1/test/rqdb")
async def test_rqdb():
    """Checks if the rqlite cluster is responding normally (2xx response)"""
    async with Itgs() as itgs:
        conn = await itgs.conn()
        res = await conn.cursor("none").execute("SELECT 2")
        if res.rowcount != 1:
            return JSONResponse(
                content={"message": f"invalid rowcount: {res.rowcount}"},
                status_code=503,
            )
        if res.results[0] != [2]:
            return JSONResponse(
                content={"message": f"invalid row: {repr(res.results[0])}"},
                status_code=503,
            )
        return JSONResponse(
            content={"message": "rqlite cluster responding normally"}, status_code=200
        )


@app.get("/api/1/test/redis")
async def test_redis():
    """Checks if the redis cluster is responding normally (2xx response)"""
    async with Itgs() as itgs:
        redis = await itgs.redis()

        test_key = "__test" + secrets.token_urlsafe(8)
        test_val = secrets.token_urlsafe(8)
        if not await redis.set(test_key, test_val):
            return JSONResponse(
                content={
                    "message": f"failed to set {test_key=} to {test_val=} (non-OK)"
                },
                status_code=503,
            )
        val: bytes = await redis.get(test_key)
        val = val.decode("utf-8")
        if val != test_val:
            return JSONResponse(
                content={
                    "message": f"expected {test_key=} to have {test_val=} but got {val=}"
                },
                status_code=503,
            )
        if not await redis.delete(test_key):
            return JSONResponse(
                content={"message": f"failed to delete {test_key=} (non-OK)"},
                status_code=503,
            )
        return JSONResponse(content={"message": "redis cluster responding normally"})


@app.get("/api/1/test/division")
async def test_division(dividend: int, divisor: int):
    """returns dividend/divisor - but gives an internal server error
    if divisor = 0; useful for testing error reporting
    """
    return JSONResponse(content={"quotient": dividend / divisor}, status_code=200)
