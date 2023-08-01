import os
import secrets
from pydantic import BaseModel, Field
from typing import Optional
from itgs import Itgs
import aiohttp
from oauth.models.oauth_state import OauthState
from oauth.settings import ProviderSettings
from redis.asyncio import Redis
from redis.exceptions import NoScriptError
import users.lib.stats
import jwt
import time
import json
import asyncio
import hashlib
import random


class InterpretedClaims(BaseModel):
    """The standard claims we look for from a provider. Note this is NOT referring
    to the claims in our jwts and should be after some processing (e.g., converting
    name to/from given_name and family_name)
    """

    sub: str = Field(description="A stable identifier")
    email: str = Field(description="An email address")
    email_verified: bool = Field(description="True if the email address is verified")
    name: Optional[str] = Field(description="A name")
    given_name: Optional[str] = Field(description="A given name")
    family_name: Optional[str] = Field(description="A family name")
    phone_number: Optional[str] = Field(description="A phone number")
    phone_number_verified: Optional[bool] = Field(
        description="True if the phone number is verified"
    )
    picture: Optional[str] = Field(
        description="A url where the users profile picture can be accessed"
    )
    iat: int = Field(
        description="The time the token was issued, in seconds since the epoch"
    )


class UserWithIdentity(BaseModel):
    user_sub: str = Field(description="Our internal sub for the user")
    identity_uid: str = Field(description="The UID of the user_identity used")


class OauthExchangeResponse(BaseModel):
    id_token: str = Field(
        description=(
            "An oseh JWT which can be passed via the Authorization header to "
            "most endpoints as a bearer token. Contains the following claims:\n"
            "- iss: _required_ the string 'oseh'\n"
            "- sub: _required_ a stable identifier for the user\n"
            "- aud: _required_ the string 'oseh-id'\n"
            "- exp: _required_ the time the token expires, in seconds since the epoch\n"
            "- iat: _required_ the time the token was issued, in seconds since the epoch\n"
            "- jti: _required_ a unique identifier for the token, for revocation\n"
            "- name: _optional_ the user's name where a legal name is appropriate\n"
            "- given_name: _optional_ the user's given name\n"
            "- family_name: _optional_ the user's family name\n"
            "- email: _optional_ the users preferred email address\n"
            "- phone_number: _optional_ the users preferred phone number\n"
        )
    )
    refresh_token: Optional[str] = Field(
        description=(
            "A refresh token which can be used to obtain a new id_token. This typically "
            "lasts much longer than an id_token (e.g., 30 days) and is only provided if "
            "requested during the preparation step. The only guarranteed claims are:\n"
            "- iss: _required_ the string 'oseh'\n"
            "- sub: _required_ a stable identifier for the user\n"
            "- aud: _required_ the string 'oseh-refresh'\n"
            "- exp: _required_ the time the token expires, in seconds since the epoch\n"
            "- iat: _required_ the time the token was issued, in seconds since the epoch\n"
            "- jti: _required_ a unique identifier for the token, for revocation\n"
        )
    )
    onboard: bool = Field(
        description="True if the user should go through the onboarding flow, false otherwise"
    )
    redirect_uri: str = Field(
        description="The URI to which the user should be redirected after the exchange"
    )


class OauthCodeInvalid(Exception):
    """Returned when the code is invalid or has expired"""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class OauthInternalException(Exception):
    """Returned when an internal error occurs"""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


async def fetch_state(itgs: Itgs, state: str) -> Optional[OauthState]:
    """Fetches the oauth state stored in redis for the given state string,
    if any exists, otherwise returns None
    """
    redis = await itgs.redis()
    state_key = f"oauth:states:{state}".encode("utf-8")
    state_info_raw: Optional[bytes] = await redis.getdel(state_key)
    if state_info_raw is None:
        return None

    return OauthState.parse_raw(state_info_raw)


async def use_standard_exchange(
    itgs: Itgs, code: str, provider: ProviderSettings, state: OauthState
) -> OauthExchangeResponse:
    async with aiohttp.ClientSession() as session:
        async with session.post(
            provider.token_endpoint,
            data=aiohttp.FormData(
                {
                    "code": code,
                    "client_id": provider.client_id,
                    "client_secret": provider.client_secret,
                    "redirect_uri": state.initial_redirect_uri,
                    "grant_type": "authorization_code",
                }
            ),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
            },
        ) as response:
            if not response.ok:
                text = await response.text()
                raise OauthCodeInvalid(
                    f"The code is invalid or has expired: {response.status} - {text}"
                )

            data: dict = await response.json()

            id_token = data["id_token"]

    claims = jwt.decode(id_token, options={"verify_signature": False})
    interpreted_claims = await interpret_provider_claims(itgs, provider, claims)
    user = await initialize_user_from_info(
        itgs, provider.name, interpreted_claims, claims
    )
    return await create_tokens_for_user(
        itgs,
        user=user,
        interpreted_claims=interpreted_claims,
        redirect_uri=state.redirect_uri,
        refresh_token_desired=state.refresh_token_desired,
    )


async def create_tokens_for_user(
    itgs: Itgs,
    user: UserWithIdentity,
    interpreted_claims: InterpretedClaims,
    redirect_uri: str,
    refresh_token_desired: bool,
) -> OauthExchangeResponse:
    """Creates the id token and optionally refresh token for the user with
    the given sub. The returned id token and refresh token are both JWTs.

    This also checks if the user should go through the onboarding flow
    and may swap their phone number if a better one is available.
    """
    conn = await itgs.conn()
    cursor = conn.cursor("none")

    response = await cursor.execute(
        """
        SELECT
            EXISTS (
                SELECT 1 FROM user_journeys
                WHERE user_journeys.user_id = users.id
            ) AS b1,
            phone_number,
            phone_number_verified,
            email,
            given_name,
            family_name
        FROM users WHERE sub = ?
        """,
        (user.user_sub, user.user_sub),
    )

    if not response.results:
        # raced with the create almost certainly, which means we can make a pretty good
        # assumption about this users state
        onboard = True
        phone_number = None
        phone_number_verified = False
        email = None
        given_name = None
        family_name = None
        name = None
    else:
        onboard: bool = not response.results[0][0]
        phone_number: Optional[str] = response.results[0][1]
        phone_number_verified: bool = bool(response.results[0][2])
        email: str = response.results[0][3]
        given_name: Optional[str] = response.results[0][4]
        family_name: Optional[str] = response.results[0][5]
        name = (
            f"{given_name} {family_name}"
            if given_name is not None and family_name is not None
            else None
        )

    now = int(time.time())
    id_token = jwt.encode(
        {
            "sub": user.user_sub,
            "iss": "oseh",
            "aud": "oseh-id",
            "exp": now + 60 * 60,
            "iat": now - 1,
            "jti": secrets.token_urlsafe(16),
            "name": name or interpreted_claims.name or "Anonymous",
            "given_name": given_name or interpreted_claims.given_name or "Anonymous",
            "family_name": family_name or interpreted_claims.family_name or "",
            "email": email or interpreted_claims.email,
            "phone_number": (
                interpreted_claims.phone_number
                if (
                    interpreted_claims.phone_number is not None
                    or not phone_number_verified
                    or phone_number is None
                )
                else phone_number
            ),
        },
        os.environ["OSEH_ID_TOKEN_SECRET"],
        algorithm="HS256",
    )

    refresh_token: Optional[str] = None

    if refresh_token_desired:
        refresh_jti = secrets.token_urlsafe(16)
        refresh_token_expires_at = now + 60 * 60 * 24 * 30
        redis = await itgs.redis()
        await sorted_set_insert_with_max_length_and_min_score(
            redis,
            key=f"oauth:valid_refresh_tokens:{user.user_sub}",
            val=refresh_jti,
            score=refresh_token_expires_at,
            max_length=10,
            min_score=now,
        )

        refresh_token = jwt.encode(
            {
                "sub": user.user_sub,
                "iss": "oseh",
                "aud": "oseh-refresh",
                "exp": refresh_token_expires_at,
                "iat": now - 1,
                "jti": refresh_jti,
                "oseh:og_exp": refresh_token_expires_at,
            },
            key=os.environ["OSEH_REFRESH_TOKEN_SECRET"],
            algorithm="HS256",
        )

    return OauthExchangeResponse(
        id_token=id_token,
        refresh_token=refresh_token,
        redirect_uri=redirect_uri,
        onboard=onboard,
    )


async def interpret_provider_claims(
    itgs: Itgs, provider: ProviderSettings, claims: dict
) -> InterpretedClaims:
    """Returns the interpreted claims from those provided by the provider"""
    sub = claims["sub"]
    email = claims["email"]
    email_verified = claims.get("email_verified", False)
    phone_number = claims.get("phone_number")
    phone_number_verified = (
        claims.get("phone_number_verified", False) if phone_number is not None else None
    )
    name: Optional[str] = claims.get("name")
    given_name: Optional[str] = claims.get("given_name")
    family_name: Optional[str] = claims.get("family_name")

    if name is None and (given_name is not None or family_name is not None):
        name = " ".join([given_name or "", family_name or ""]).strip()

    if name is not None and (given_name is None or family_name is None):
        try:
            implied_given_name, implied_family_name = name.split(" ", 1)
        except ValueError:
            implied_given_name, implied_family_name = name, ""

        given_name = given_name or implied_given_name
        family_name = family_name or implied_family_name

    if given_name is None:
        given_name = "Anonymous"

    if family_name is None:
        family_name = ""

    picture: Optional[str] = claims.get("picture")
    iat: int = int(claims.get("iat", time.time()))

    return InterpretedClaims(
        sub=sub,
        email=email,
        email_verified=email_verified,
        name=name,
        given_name=given_name,
        family_name=family_name,
        phone_number=phone_number,
        phone_number_verified=phone_number_verified,
        picture=picture,
        iat=iat,
    )


async def initialize_user_from_info(
    itgs: Itgs,
    provider: str,
    interpreted_claims: InterpretedClaims,
    example_claims: Optional[dict] = None,
) -> UserWithIdentity:
    """Returns the sub we use to identify the user with the given claims from
    the given provider. If no such user exists, then one is created.

    If example_claims is specified, it's stored in the `example_claims` column
    of the identity, for debugging. If not specified, it's created from the
    interpreted claims, though this may make debugging more difficult.
    """

    if example_claims is None:
        example_claims = {
            "sub": interpreted_claims.sub,
            "iat": interpreted_claims.iat,
            "email": interpreted_claims.email,
            "email_verified": interpreted_claims.email_verified,
            "phone_number": interpreted_claims.phone_number,
            "phone_number_verified": interpreted_claims.phone_number_verified,
            "given_name": interpreted_claims.given_name,
            "family_name": interpreted_claims.family_name,
            "picture": interpreted_claims.picture,
            "oseh:interpreted": True,
        }

    conn = await itgs.conn()

    # no read consistency is required for avoiding corruption due to the
    # defensive technique below. we will upgrade to weak if the first insert
    # fails
    cursor = conn.cursor("none")

    for _ in range(5):
        response = await cursor.execute(
            """
            SELECT
              users.sub,
              user_identities.uid
            FROM user_identities
            JOIN users ON users.id = user_identities.user_id
            WHERE
                user_identities.sub = ? AND user_identities.provider = ?
            """,
            (interpreted_claims.sub, provider),
        )

        if response.results is not None and len(response.results) > 0:
            user_sub: str = response.results[0][0]
            identity_uid: str = response.results[0][1]
            await cursor.execute(
                "UPDATE user_identities SET example_claims=?, last_seen_at=? WHERE uid=? AND last_seen_at < ?",
                (
                    json.dumps(example_claims, sort_keys=True),
                    interpreted_claims.iat,
                    identity_uid,
                    interpreted_claims.iat,
                ),
            )

            if interpreted_claims.picture is not None:
                redis = await itgs.redis()
                await redis.set(
                    f"users:{user_sub}:checking_profile_image".encode("utf-8"),
                    b"1",
                    ex=10,
                )
                jobs = await itgs.jobs()
                await jobs.enqueue(
                    "runners.check_profile_picture",
                    user_sub=user_sub,
                    picture_url=interpreted_claims.picture,
                    jwt_iat=interpreted_claims.iat,
                )

            return UserWithIdentity(user_sub=user_sub, identity_uid=identity_uid)

        new_user_sub = f"oseh_u_{secrets.token_urlsafe(16)}"
        new_identity_uid = f"oseh_ui_{secrets.token_urlsafe(16)}"
        new_revenue_cat_id = f"oseh_u_rc_{secrets.token_urlsafe(16)}"
        now = time.time()
        response = await cursor.executemany3(
            (
                (
                    """
                    INSERT INTO users (
                        sub, email, email_verified, phone_number, phone_number_verified,
                        given_name, family_name, admin, revenue_cat_id, created_at
                    )
                    SELECT
                        ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?
                    WHERE
                        NOT EXISTS (
                            SELECT 1 FROM user_identities WHERE user_identities.sub = ? AND user_identities.provider = ?
                        )
                    """,
                    (
                        new_user_sub,
                        interpreted_claims.email,
                        interpreted_claims.email_verified,
                        interpreted_claims.phone_number,
                        interpreted_claims.phone_number_verified,
                        interpreted_claims.given_name,
                        interpreted_claims.family_name,
                        0,
                        new_revenue_cat_id,
                        now,
                        interpreted_claims.sub,
                        provider,
                    ),
                ),
                (
                    """
                    INSERT INTO user_identities (
                        uid, user_id, provider, sub, example_claims, created_at, last_seen_at
                    )
                    SELECT
                        ?, users.id, ?, ?, ?, ?, ?
                    FROM users
                    WHERE users.sub = ?
                    """,
                    (
                        new_identity_uid,
                        provider,
                        interpreted_claims.sub,
                        json.dumps(example_claims, sort_keys=True),
                        now,
                        interpreted_claims.iat,
                        new_user_sub,
                    ),
                ),
            )
        )
        if response[0].rows_affected is not None and response[0].rows_affected > 0:
            jobs = await itgs.jobs()
            await jobs.enqueue("runners.revenue_cat.ensure_user", user_sub=new_user_sub)
            await jobs.enqueue("runners.klaviyo.ensure_user", user_sub=new_user_sub)
            await users.lib.stats.on_user_created(itgs, new_user_sub, now)

            if interpreted_claims.picture is not None:
                redis = await itgs.redis()
                await redis.set(
                    f"users:{new_user_sub}:checking_profile_image".encode("utf-8"),
                    b"1",
                    ex=10,
                )
                await jobs.enqueue(
                    "runners.check_profile_picture",
                    user_sub=new_user_sub,
                    picture_url=interpreted_claims.picture,
                    jwt_iat=interpreted_claims.iat,
                )

            return UserWithIdentity(
                user_sub=new_user_sub, identity_uid=new_identity_uid
            )

        cursor.read_consistency = "weak"
        await asyncio.sleep(0.1 + 0.1 * random.random())
    else:
        raise OauthInternalException(
            "Failed to initialize user - too many concurrent modifications"
        )


SORTED_SET_INSERT_WITH_MAX_LENGTH_AND_MIN_SCORE_SCRIPT = """
local key = KEYS[1]
local max_length = tonumber(ARGV[1])
local min_score = tonumber(ARGV[2])
local value = ARGV[3]
local score = tonumber(ARGV[4])

redis.call("ZADD", key, score, value)
redis.call("ZREMRANGEBYSCORE", key, "-inf", min_score)

local current_length = redis.call("ZCARD", key)
if current_length > max_length then
    redis.call("ZREMRANGEBYRANK", key, 0, 0)
    current_length = current_length - 1
end

if current_length > 0 then
    local highest_score = redis.call("ZRANGE", key, -1, -1, "WITHSCORES")[2]
    redis.call("EXPIREAT", key, tonumber(highest_score))
end

return 1
"""

SORTED_SET_INSERT_WITH_MAX_LENGTH_AND_MIN_SCORE_SCRIPT_SHA = hashlib.sha1(
    SORTED_SET_INSERT_WITH_MAX_LENGTH_AND_MIN_SCORE_SCRIPT.encode("utf-8")
).hexdigest()


async def sorted_set_insert_with_max_length_and_min_score(
    redis: Redis, key: str, val: str, score: int, *, max_length: int, min_score: int
) -> None:
    """Inserts the given value into the sorted set with the given key, then
    removes all values with a score at or below min_score, then finally
    removes the lowest-scoring value if the set is now longer than
    max_length. If the key exists after this process, its set to expire
    at the new largest score.

    Args:
        redis (Redis): The redis client to use.
        key (str): The key of the sorted set.
        val (str): The value to insert.
        score (int): The score to insert.
        max_length (int): The maximum length of the sorted set.
        min_score (int): The minimum score of the sorted set.
    """

    evalsha_args = [
        SORTED_SET_INSERT_WITH_MAX_LENGTH_AND_MIN_SCORE_SCRIPT_SHA,
        1,
        key.encode("utf-8"),
        str(max_length).encode("ascii"),
        str(min_score).encode("ascii"),
        val.encode("utf-8"),
        str(score).encode("ascii"),
    ]

    try:
        await redis.evalsha(*evalsha_args)
    except NoScriptError:
        true_hash = await redis.script_load(
            SORTED_SET_INSERT_WITH_MAX_LENGTH_AND_MIN_SCORE_SCRIPT
        )
        if true_hash != SORTED_SET_INSERT_WITH_MAX_LENGTH_AND_MIN_SCORE_SCRIPT_SHA:
            raise Exception(
                f"sorted set insert script hash mismatch: {true_hash=} != {SORTED_SET_INSERT_WITH_MAX_LENGTH_AND_MIN_SCORE_SCRIPT_SHA=}"
            )

        await redis.evalsha(*evalsha_args)
