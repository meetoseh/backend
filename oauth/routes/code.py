import hashlib
import time
from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal
from models import StandardErrorResponse
from redis.asyncio import Redis
from redis.exceptions import NoScriptError
from itgs import Itgs
from csrf import BAD_CSRF_TYPE, check_csrf
from timing_attacks import coarsen_time_with_sleeps
from oauth.lib.clients import check_client
import base64
import hmac
import secrets
import json


router = APIRouter()


class OauthCodeFromPasswordRequest(BaseModel):
    email: str = Field(
        description="The email of the user to log in", min_length=1, max_length=511
    )
    password: str = Field(
        description="The password of the user to log in", min_length=1, max_length=1023
    )
    client_id: str = Field(
        description="The id of the client who will eventually receive the code",
        min_length=1,
        max_length=63,
    )
    redirect_uri: str = Field(
        description="The uri the user is going to be redirected to",
        min_length=1,
        max_length=2047,
    )
    csrf: str = Field(
        description=(
            "A token that is annoying to generate by third-parties but is "
            "easy for us to generate. Disincentivizes third-parties from "
            "using this endpoint directly"
        )
    )


class OauthCodeFromPasswordResponse(BaseModel):
    code: str = Field(
        description="The code to use to get an access token",
    )


class KeyDerivationMethod(BaseModel):
    name: Literal["pbkdf2_hmac"] = Field(description="The name of the method")
    hash_name: Literal["sha1"] = Field(description="The name of the hash function")
    salt: str = Field(description="The salt used to derive the key", min_length=32)
    iterations: int = Field(description="The number of iterations to use", ge=100_000)


ERROR_401_TYPES = Literal["invalid_credentials"]
INVALID_CREDENTIALS_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_401_TYPES](
        type="invalid_credentials",
        message="Email or password is incorrect",
    ).json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=401,
)

ERROR_403_TYPES = Literal["invalid_client"]
INVALID_CLIENT_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_403_TYPES](
        type="invalid_client",
        message="Invalid client id or redirect uri",
    ).json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=403,
)

ERROR_429_TYPES = Literal["too_many_attempts"]
TOO_MANY_ATTEMPTS_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_429_TYPES](
        type="too_many_attempts",
        message="Too many login attempts recently. Try again in a bit",
    ).json(),
    headers={"Content-Type": "application/json; charset=utf-8", "Retry-After": "60"},
    status_code=429,
)


@router.post(
    "/code",
    response_model=OauthCodeFromPasswordResponse,
    responses={
        "400": {
            "description": "Bad CSRF token",
            "model": StandardErrorResponse[BAD_CSRF_TYPE],
        },
        "401": {
            "description": "Email or password is incorrect",
            "model": StandardErrorResponse[ERROR_401_TYPES],
        },
        "403": {
            "description": "Invalid client id or redirect uri",
            "model": StandardErrorResponse[ERROR_403_TYPES],
        },
        "429": {
            "description": "Too many login attempts recently. Try again in a bit",
            "model": StandardErrorResponse[ERROR_429_TYPES],
        },
    },
)
async def get_oauth_code_from_password(args: OauthCodeFromPasswordRequest):
    """A simple endpoint to get an oauth 2.0 code from an email/password. Only
    intended to be used directly by https://oseh.io - a third party would
    instead use https://oseh.io/authorize as the authorization endpoint to
    redirect back to your site with a code.
    """
    async with Itgs() as itgs:
        csrf_response = await check_csrf(itgs, args.csrf)
        if not csrf_response.success:
            return csrf_response.error_response

        if not await check_client(
            itgs, client_id=args.client_id, redirect_uri=args.redirect_uri
        ):
            return INVALID_CLIENT_RESPONSE

        if not await check_user_login_ratelimit(itgs, args.email):
            return TOO_MANY_ATTEMPTS_RESPONSE

        if not await check_global_login_ratelimit(itgs, time.time()):
            return TOO_MANY_ATTEMPTS_RESPONSE

        async with coarsen_time_with_sleeps(1):
            conn = await itgs.conn()
            cursor = conn.cursor("weak")

            result = await cursor.execute(
                """
                SELECT
                    uid,
                    email_verified_at,
                    key_derivation_method,
                    derived_password
                FROM direct_accounts
                WHERE email=?
                """,
                (args.email,),
            )

            if not result.results:
                return INVALID_CREDENTIALS_RESPONSE

            uid: str = result.results[0][0]
            email_verified_at: float = result.results[0][1]
            key_derivation_method_raw: str = result.results[0][2]
            correct_derived_password: bytes = base64.b64decode(result.results[0][3])

            key_derivation_method = KeyDerivationMethod.parse_raw(
                key_derivation_method_raw, content_type="application/json"
            )

            received_derived_password = hashlib.pbkdf2_hmac(
                key_derivation_method.hash_name,
                args.password.encode("utf-8"),
                base64.b64decode(key_derivation_method.salt),
                key_derivation_method.iterations,
            )

            if not hmac.compare_digest(
                received_derived_password, correct_derived_password
            ):
                return INVALID_CREDENTIALS_RESPONSE

            code = secrets.token_urlsafe(16)

            redis = await itgs.redis()
            exp_at = int(time.time()) + 60
            await redis.set(
                f"oauth:direct_account:code:{args.client_id}:{code}",
                json.dumps(
                    {
                        "redirect_uri": args.redirect_uri,
                        "sub": uid,
                        "email": args.email,
                        "email_verified": email_verified_at is not None,
                        "expires_at": exp_at,
                    }
                ),
                exat=exp_at,
            )
            return Response(
                content=OauthCodeFromPasswordResponse(code=code).json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=200,
            )


ADD_PRUNE_GLOBAL_RATELIMIT_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])

redis.call('rpush', key, now)
local current_length = redis.call('llen', key)
while (current_length > 100) or (tonumber(redis.call('lindex', key, 0)) < now - 60) do
  current_length = current_length - 1
  redis.call('lpop', key)
end
return current_length
"""
ADD_PRUNE_GLOBAL_RATELIMIT_SHA = hashlib.sha1(
    ADD_PRUNE_GLOBAL_RATELIMIT_SCRIPT.encode("utf-8")
).hexdigest()


async def add_prune_global_ratelimit(redis: Redis, now: float) -> int:
    eval_args = (
        ADD_PRUNE_GLOBAL_RATELIMIT_SHA,
        1,
        b"oauth:direct_account:login_attempts",
        now,
    )
    try:
        result = await redis.evalsha(*eval_args)
    except NoScriptError:
        await redis.script_load(ADD_PRUNE_GLOBAL_RATELIMIT_SCRIPT)
        result = await redis.evalsha(*eval_args)
    return int(result)


async def check_global_login_ratelimit(itgs: Itgs, now: float) -> bool:
    """Adds a login attempt at the given time to the global login window,
    and returns true if the attempt should be allowed and false otherwise
    """
    redis = await itgs.redis()
    attempts = await add_prune_global_ratelimit(redis, now)
    return attempts <= 60


async def check_user_login_ratelimit(itgs: Itgs, email: str) -> bool:
    """Adds a login attempt to the user with the given email and returns
    true if the attempt should be allowed and false otherwise
    """
    redis = await itgs.redis()
    key = f"oauth:direct_account:login_attempts:{email}".encode("utf-8")

    async with redis.pipeline() as pipe:
        pipe.multi()
        await pipe.incr(key)
        await pipe.expire(key, 300)
        attempts, _ = await pipe.execute()

    return attempts < 5
