import os
import jwt
import time
from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response
from starlette.middleware.cors import CORSMiddleware
from error_middleware import handle_request_error, handle_error
from itgs import Itgs
import secrets
import updater
import users.lib.entitlements
import migrations.main
import multiprocessing
import continuous_deployment.router
import users.router
import image_files.router
import journeys.router
import file_uploads.router
import content_files.router
import instructors.router
import daily_events.router
import admin.router
import admin.routes.read_journey_subcategory_view_stats
import urllib.parse
import asyncio

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


multiprocessing.Process(target=updater.listen_forever_sync, daemon=True).start()
multiprocessing.Process(target=migrations.main.main_sync, daemon=True).start()
multiprocessing.Process(
    target=users.lib.entitlements.purge_cache_loop_sync, daemon=True
).start()
multiprocessing.Process(
    target=admin.routes.read_journey_subcategory_view_stats.listen_available_responses_forever_sync,
    daemon=True,
).start()
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
        allow_methods=["GET", "POST", "HEAD", "PUT", "DELETE"],
        allow_headers=["Authorization", "Pragma"],
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
app.include_router(
    daily_events.router.router, prefix="/api/1/daily_events", tags=["daily_events"]
)
app.include_router(admin.router.router, prefix="/api/1/admin", tags=["admin"])
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


@app.post("/api/1/test/dev_login")
async def dev_login(sub: str):
    """returns an id token under the id key for the given subject; only works in
    development mode"""
    if os.environ.get("ENVIRONMENT") != "dev":
        return Response(status_code=403)
    now = time.time()
    encoded_jwt = jwt.encode(
        {
            "sub": sub,
            "iss": os.environ["EXPECTED_ISSUER"],
            "exp": now + 3600,
            "aud": os.environ["AUTH_CLIENT_ID"],
            "given_name": "Timothy",
            "family_name": "Moore",
            "email": "tj@meetoseh.com",
            "email_verified": True,
            "picture": (
                # i prefer this avatar :o
                "https://avatars.dicebear.com/api/adventurer/tj-%40-meetoseh.svg"
                if sub == "timothy"
                else f"https://avatars.dicebear.com/api/bottts/{urllib.parse.quote(sub)}.svg"
            ),
            "iat": now,
            "token_use": "id",
        },
        os.environ["DEV_SECRET_KEY"],
        algorithm="HS256",
    )
    return JSONResponse(content={"id": encoded_jwt}, status_code=200)
