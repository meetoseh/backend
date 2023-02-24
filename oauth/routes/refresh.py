from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal, Optional
from models import StandardErrorResponse
from error_middleware import handle_error
from itgs import Itgs
from redis.asyncio import Redis
from redis.exceptions import NoScriptError
import hashlib
import secrets
import time
import jwt
import os


router = APIRouter()


class RefreshRequest(BaseModel):
    refresh_token: str = Field(
        description="The refresh token to use to get a new id token"
    )


class RefreshResponse(BaseModel):
    id_token: str = Field(description="The new id token")
    refresh_token: str = Field(description="The new refresh token for future refreshes")


ERROR_403_TYPES = Literal["unknown_token", "too_close_to_expiration"]
UNKNOWN_TOKEN = Response(
    content=StandardErrorResponse[ERROR_403_TYPES](
        type="unknown_token",
        message="That refresh token is invalid, expired, or revoked.",
    ).json(),
    status_code=403,
)
TOO_CLOSE_TO_EXPIRATION = Response(
    content=StandardErrorResponse[ERROR_403_TYPES](
        type="too_close_to_expiration",
        message="That refresh token is too close to expiration to be refreshed.",
    ).json(),
    status_code=403,
)


@router.post(
    "/refresh",
    response_model=RefreshResponse,
    responses={
        "403": {
            "description": "The refresh token is invalid, expired, or revoked.",
            "model": StandardErrorResponse[ERROR_403_TYPES],
        }
    },
)
async def refresh(args: RefreshRequest):
    """Uses the given refresh token to get a new id token. This revokes the
    old refresh token and issues a new one to prevent replay attacks and
    to effectively shorten the refresh token's lifespan without inconveniencing
    the user.

    This can be used to extend the life of refresh tokens up to 60 days past
    the original refresh tokens expiration. Clients should be cautious about
    not getting in a refresh loop when the refresh token is close to its maximum
    extension, i.e., when this endpoint returns a new refresh token and id token
    which is close to expiration. This can handled by looking at the `oseh:og_exp`
    claim in the refresh token or by checking the effective duration (exp - iat)
    of the returned tokens.
    """
    async with Itgs() as itgs:
        # verify locally that the refresh token appears legitimate
        try:
            payload = jwt.decode(
                args.refresh_token,
                key=os.environ["OSEH_REFRESH_TOKEN_SECRET"],
                algorithms=["HS256"],
                options={
                    "require": [
                        "sub",
                        "iss",
                        "aud",
                        "exp",
                        "iat",
                        "jti",
                        "oseh:og_exp",
                    ],
                },
                audience="oseh-refresh",
                issuer="oseh",
            )
        except Exception as e:
            if not isinstance(e, jwt.exceptions.ExpiredSignatureError):
                await handle_error(e, extra_info="failed to decode refresh token")
            else:
                await handle_error(
                    e, extra_info=f"refresh token expired: {args.refresh_token}"
                )
            return UNKNOWN_TOKEN

        # generate the new refresh token PRIOR to verifying the previous
        # one is not revoked, since we want to cycle atomically

        now = int(time.time())
        # allow extending the refresh token an additional 60 days
        new_refresh_expires_at = min(
            payload["oseh:og_exp"] + 60 * 60 * 24 * 60, now + 60 * 60 * 24 * 30
        )

        if new_refresh_expires_at - now < 30:
            slack = await itgs.slack()
            await slack.send_web_error_message(
                f"Rejecting refresh token (too close to expiration): {args.refresh_token}"
            )
            return TOO_CLOSE_TO_EXPIRATION

        new_jti = secrets.token_urlsafe(16)
        new_refresh_token = jwt.encode(
            {
                "sub": payload["sub"],
                "iss": "oseh",
                "aud": "oseh-refresh",
                "exp": new_refresh_expires_at,
                "iat": now - 1,
                "jti": new_jti,
                "oseh:og_exp": payload["oseh:og_exp"],
            },
            key=os.environ["OSEH_REFRESH_TOKEN_SECRET"],
            algorithm="HS256",
        )

        # cycle the refresh token, which verifies that the old one is actually
        # valid

        redis = await itgs.redis()
        exchange_successful = await sorted_set_exchange_and_expire_with_score(
            redis,
            f"oauth:valid_refresh_tokens:{payload['sub']}",
            payload["jti"],
            new_jti,
            now,
        )
        if not exchange_successful:
            slack = await itgs.slack()
            await slack.send_web_error_message(
                f"Rejecting refresh token (revoked): {args.refresh_token}"
            )
            return UNKNOWN_TOKEN

        # fetch required information for new id token
        conn = await itgs.conn()
        cursor = conn.cursor("weak")

        response = await cursor.execute(
            """
            SELECT given_name, family_name, email, phone_number
            FROM users WHERE sub=?
            """,
            (payload["sub"],),
        )
        if not response.results:
            # user was deleted since the refresh token was issued; revoke all tokens
            # and return an error
            await redis.delete(f"oauth:valid_refresh_tokens:{payload['sub']}")
            slack = await itgs.slack()
            await slack.send_web_error_message(
                f"Rejecting refresh token (user deleted): {args.refresh_token}"
            )
            return UNKNOWN_TOKEN

        given_name: Optional[str] = response.results[0][0]
        family_name: Optional[str] = response.results[0][1]
        email: str = response.results[0][2]
        phone_number: Optional[str] = response.results[0][3]

        name: Optional[str] = None
        if given_name is not None or family_name is not None:
            name = " ".join(
                n for n in [given_name, family_name] if n is not None
            ).strip()

        # generate the new id token
        new_id_token = jwt.encode(
            {
                "sub": payload["sub"],
                "iss": "oseh",
                "aud": "oseh-id",
                "exp": min(now + 60 * 60, new_refresh_expires_at),
                "iat": now - 1,
                "jti": secrets.token_urlsafe(16),
                "name": name,
                "given_name": given_name,
                "family_name": family_name,
                "email": email,
                "phone_number": phone_number,
            },
            os.environ["OSEH_ID_TOKEN_SECRET"],
            algorithm="HS256",
        )

        return Response(
            content=RefreshResponse(
                id_token=new_id_token,
                refresh_token=new_refresh_token,
            ).json(),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
            status_code=200,
        )


SORTED_SET_EXCHANGE_AND_EXPIRE_WITH_SCORE = """
local key = KEYS[1]
local old_value = ARGV[1]
local new_value = ARGV[2]
local new_score = tonumber(ARGV[3])

local num_removed = redis.call("ZREM", key, old_value)
if tonumber(num_removed) < 1 then
    return 0
end

redis.call("ZADD", key, new_score, new_value)

local new_biggest_score = redis.call("ZRANGE", key, -1, -1, "WITHSCORES")[2]
redis.call("EXPIREAT", key, tonumber(new_biggest_score))

return 1
"""

SORTED_SET_EXCHANGE_AND_EXPIRE_WITH_SCORE_SHA1 = hashlib.sha1(
    SORTED_SET_EXCHANGE_AND_EXPIRE_WITH_SCORE.encode("utf-8")
).hexdigest()


async def sorted_set_exchange_and_expire_with_score(
    redis: Redis, key: str, old_value: str, new_value: str, new_score: int
) -> bool:
    """Exchanges the given old value for the given new value in the given
    sorted set, but only if the old value is present. Returns True if the
    exchange was successful, False otherwise.

    If the exchange completes successfully, the sorted set is set to expire
    at the new largest score within the set.

    This cannot be done in a pipeline unless the script is loaded into Redis
    prior to this call.
    """
    evalsha_args = (
        SORTED_SET_EXCHANGE_AND_EXPIRE_WITH_SCORE_SHA1,
        1,
        key.encode("utf-8"),
        old_value.encode("utf-8"),
        new_value.encode("utf-8"),
        str(new_score).encode("ascii"),
    )
    try:
        result = await redis.evalsha(*evalsha_args)
    except NoScriptError:
        correct_hash = await redis.script_load(
            SORTED_SET_EXCHANGE_AND_EXPIRE_WITH_SCORE
        )
        if correct_hash != SORTED_SET_EXCHANGE_AND_EXPIRE_WITH_SCORE_SHA1:
            raise Exception(
                f"Script hash mismatch: {correct_hash=} != {SORTED_SET_EXCHANGE_AND_EXPIRE_WITH_SCORE_SHA1=}"
            )

        result = await redis.evalsha(*evalsha_args)

    return int(result) == 1
