from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal, Optional
from lib.contact_methods.user_current_email import select_best_current_email
from lib.contact_methods.user_current_phone import select_best_current_phone
from lib.contact_methods.user_primary_email import primary_email_join_clause
from lib.contact_methods.user_primary_phone import primary_phone_join_clause
from models import StandardErrorResponse
from error_middleware import handle_error
from itgs import Itgs
from redis.asyncio import Redis
from redis.exceptions import NoScriptError
from pypika import Table, Query, Parameter
import hashlib
import secrets
import time
import jwt
import os

from oauth.lib.feature_flags import get_feature_flags


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
    ).model_dump_json(),
    status_code=403,
)
TOO_CLOSE_TO_EXPIRATION = Response(
    content=StandardErrorResponse[ERROR_403_TYPES](
        type="too_close_to_expiration",
        message="That refresh token is too close to expiration to be refreshed.",
    ).model_dump_json(),
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

        if payload["iat"] < 1679589900:
            # bug caused us to issue invalid tokens because we related user_identities to
            # the wrong user
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

        new_refresh_jti = secrets.token_urlsafe(16)
        # cycle the refresh token, which verifies that the old one is actually
        # valid

        redis = await itgs.redis()
        exchange_successful = await sorted_set_exchange_and_expire_with_score(
            redis,
            f"oauth:valid_refresh_tokens:{payload['sub']}",
            payload["jti"],
            new_refresh_jti,
            new_refresh_expires_at,
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

        users = Table("users")
        user_email_addresses = Table("user_email_addresses")
        user_phone_numbers = Table("user_phone_numbers")

        primary_emails = user_email_addresses.as_("primary_emails")
        primary_phones = user_phone_numbers.as_("primary_phones")
        claim_emails = user_email_addresses.as_("claim_emails")
        claim_phones = user_phone_numbers.as_("claim_phones")

        query = (
            Query.from_(users)
            .select(
                users.given_name,
                users.family_name,
                primary_emails.email,
                primary_emails.verified,
                primary_phones.phone_number,
                primary_phones.verified,
            )
            .left_outer_join(primary_emails)
            .on(primary_email_join_clause(user_email_addresses=primary_emails))
            .left_outer_join(primary_phones)
            .on(primary_phone_join_clause(user_phone_numbers=primary_phones))
            .where(users.sub == Parameter("?"))
        )
        qargs = []
        checked_claim_email = payload.get("email") is not None and not payload.get(
            "email_verified", False
        )
        checked_claim_phone = payload.get(
            "phone_number"
        ) is not None and not payload.get("phone_number_verified", False)

        if checked_claim_email:
            query = query.select(claim_emails.verified)
            query = query.left_outer_join(claim_emails).on(
                (claim_emails.user_id == users.id)
                & (claim_emails.email == Parameter("?"))
            )
            qargs.append(payload["email"])

        if checked_claim_phone:
            query = query.select(claim_phones.verified)
            query = query.left_outer_join(claim_phones).on(
                (claim_phones.user_id == users.id)
                & (claim_phones.phone_number == Parameter("?"))
            )
            qargs.append(payload["phone_number"])

        qargs.append(payload["sub"])

        response = await cursor.execute(query.get_sql(), qargs)
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
        email: Optional[str] = response.results[0][2]
        email_verified: bool = bool(response.results[0][3])
        phone_number: Optional[str] = response.results[0][4]
        phone_number_verified: bool = bool(response.results[0][5])
        claim_email_verified: Optional[bool] = None
        claim_phone_verified: Optional[bool] = None

        idx = 6
        if checked_claim_email:
            claim_email_verified = bool(response.results[0][idx])
            idx += 1

        if checked_claim_phone:
            claim_phone_verified = bool(response.results[0][idx])
            idx += 1

        jwt_email, jwt_email_verified = select_best_current_email(
            payload.get("email"),
            bool(payload.get("email_verified")) or bool(claim_email_verified),
            email,
            email_verified,
        )

        jwt_phone, jwt_phone_verified = select_best_current_phone(
            payload.get("phone_number"),
            bool(payload.get("phone_number_verified")) or bool(claim_phone_verified),
            phone_number,
            phone_number_verified,
        )

        name: Optional[str] = None
        if given_name is not None or family_name is not None:
            name = " ".join(
                n for n in [given_name, family_name] if n is not None
            ).strip()

        user_info_claims = {
            **(
                {}
                if jwt_email is None
                else {
                    "email": jwt_email,
                    "email_verified": jwt_email_verified,
                }
            ),
            **(
                {}
                if jwt_phone is None
                else {
                    "phone_number": jwt_phone,
                    "phone_number_verified": jwt_phone_verified,
                }
            ),
        }

        # generate the new tokens
        new_refresh_token = jwt.encode(
            {
                "sub": payload["sub"],
                "iss": "oseh",
                "aud": "oseh-refresh",
                "exp": new_refresh_expires_at,
                "iat": now - 1,
                "jti": new_refresh_jti,
                "oseh:og_exp": payload["oseh:og_exp"],
                **user_info_claims,
            },
            key=os.environ["OSEH_REFRESH_TOKEN_SECRET"],
            algorithm="HS256",
        )
        feature_flags = await get_feature_flags(
            itgs,
            user_sub=payload["sub"],
            email=jwt_email,
            email_verified=jwt_email_verified,
        )

        new_id_jti = secrets.token_urlsafe(16)
        new_id_token = jwt.encode(
            {
                "sub": payload["sub"],
                "iss": "oseh",
                "aud": "oseh-id",
                "exp": min(now + 60 * 60, new_refresh_expires_at),
                "iat": now - 1,
                "jti": new_id_jti,
                "name": name,
                "given_name": given_name,
                "family_name": family_name,
                **user_info_claims,
                **(
                    {}
                    if feature_flags is None
                    else {"oseh:feature_flags": feature_flags}
                ),
            },
            os.environ["OSEH_ID_TOKEN_SECRET"],
            algorithm="HS256",
        )

        return Response(
            content=RefreshResponse(
                id_token=new_id_token,
                refresh_token=new_refresh_token,
            ).model_dump_json(),
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
redis.call("EXPIREAT", key, math.ceil(tonumber(new_biggest_score)))

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
        result = await redis.evalsha(*evalsha_args)  # type: ignore
    except NoScriptError:
        correct_hash = await redis.script_load(
            SORTED_SET_EXCHANGE_AND_EXPIRE_WITH_SCORE
        )
        if correct_hash != SORTED_SET_EXCHANGE_AND_EXPIRE_WITH_SCORE_SHA1:
            raise Exception(
                f"Script hash mismatch: {correct_hash=} != {SORTED_SET_EXCHANGE_AND_EXPIRE_WITH_SCORE_SHA1=}"
            )

        result = await redis.evalsha(*evalsha_args)  # type: ignore

    return int(result) == 1
