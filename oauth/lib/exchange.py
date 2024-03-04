import os
import secrets
import phonenumbers
from pydantic import BaseModel, Field, validator
from dataclasses import dataclass
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    Literal,
    Optional,
    Sequence,
    Union,
)
from error_middleware import handle_warning
from itgs import Itgs
import aiohttp
from lib.contact_methods.contact_method_stats import (
    ContactMethodStatsPreparer,
    contact_method_stats,
)
from lib.contact_methods.user_current_email import select_best_current_email
from lib.contact_methods.user_current_phone import select_best_current_phone
from lib.contact_methods.user_primary_email import primary_email_join_clause
from lib.contact_methods.user_primary_phone import primary_phone_join_clause
from lib.daily_reminders.registration_stats import (
    DailyReminderRegistrationStatsPreparer,
)
from lib.redis_stats_preparer import RedisStatsPreparer
from lib.shared.clean_for_slack import clean_for_slack
from lib.shared.describe_user import enqueue_send_described_user_slack_message
from oauth.models.oauth_state import OauthState
from oauth.settings import ProviderSettings
from redis.asyncio import Redis
from redis.exceptions import NoScriptError
from pypika import Table, Query, Parameter
from pypika.terms import ExistsCriterion
from loguru import logger
import oauth.lib.merging.start_merge_auth
import users.lib.stats
import jwt
import time
import json
import asyncio
import hashlib
import unix_dates
import random
import pytz
from functools import partial
from rqdb.result import ResultItem

tz = pytz.timezone("America/Los_Angeles")


class InterpretedClaims(BaseModel):
    """The standard claims we look for from a provider. Note this is NOT referring
    to the claims in our jwts and should be after some processing (e.g., converting
    name to/from given_name and family_name)
    """

    sub: str = Field(description="A stable identifier")
    email: Optional[str] = Field(description="An email address")
    email_verified: Optional[bool] = Field(
        description="True if the email address is verified"
    )
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

    @validator("phone_number")
    def set_none_if_not_e164(cls, v):
        if os.environ["ENVIRONMENT"] == "dev" and v == "+15555555555":
            return v
        try:
            parsed = phonenumbers.parse(v)
            if not phonenumbers.is_valid_number(parsed):
                return None
            return phonenumbers.format_number(
                parsed, phonenumbers.PhoneNumberFormat.E164
            )
        except:
            return None

    @validator("email_verified")
    def email_verified_false_if_unset_and_email_provided(cls, v, values):
        if v is None and values.get("email") is not None:
            return False
        if v is not None and values.get("email") is None:
            return None
        return v

    @validator("phone_number_verified")
    def phone_number_verified_false_if_unset_and_phone_number_provided(cls, v, values):
        if v is None and values.get("phone_number") is not None:
            return False
        if v is not None and values.get("phone_number") is None:
            return None
        return v


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
            "- oseh:feature_flags: _optional_ a list of strings, each representing a feature flag\n"
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


class OauthMergeExchangeResponse(BaseModel):
    merge_jwt: str = Field(
        description=(
            "A specialized JWT that the original user can pass along with valid authorization "
            "for the original account in order to attempt the merge process."
        )
    )
    """A JWT created as if by oauth.lib.start_merge_auth.create_jwt"""


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

    return OauthState.model_validate_json(state_info_raw)


async def use_standard_exchange(
    itgs: Itgs, code: str, provider: ProviderSettings, state: OauthState
) -> OauthExchangeResponse:
    """Performs the standard exchange of a code from the given provider for
    on Oseh platform id token and refresh token. This will ignore
    `state.merging_with_user_sub`
    """
    claims = await fetch_provider_token_claims(itgs, code, provider, state)
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


async def use_standard_merge_exchange(
    itgs: Itgs, code: str, provider: ProviderSettings, state: OauthState
) -> OauthMergeExchangeResponse:
    """Performs the standard merge-exchange of a code from the given provider
    to associate the identity with the user with sub `state.merging_with_user_sub`.
    """
    assert (
        state.merging_with_user_sub is not None
    ), "cannot use merge exchange without original user sub"
    claims = await fetch_provider_token_claims(itgs, code, provider, state)
    merge_jwt = await oauth.lib.merging.start_merge_auth.create_jwt(
        itgs,
        original_user_sub=state.merging_with_user_sub,
        provider=provider.name,
        provider_claims=claims,
    )
    return OauthMergeExchangeResponse(
        merge_jwt=merge_jwt,
    )


async def fetch_provider_token_claims(
    itgs: Itgs, code: str, provider: ProviderSettings, state: OauthState
) -> Dict[str, Any]:
    """Uses the given code to fetch an id token from the given provider
    which can be decoded to get the claims. We don't validate the signature
    of the token as it was received over a secure connection (and we don't
    necessarily have a way to verify the signature anyway, and whatever we
    did do would also rely on TLS).

    Args:
        itgs (Itgs): the integrations to (re)use
        code (str): the code to exchange
        provider (ProviderSettings): the provider to use
        state (OauthState): the state associated with the secret received from
            the client

    Returns:
        dict[str, Any]: The claims from the provider

    Raises:
        OauthCodeInvalid: if the code is invalid or has expired
    """
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

    return jwt.decode(id_token, options={"verify_signature": False})


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

    users = Table("users")
    user_journeys = Table("user_journeys")
    primary_emails = Table("user_email_addresses").as_("primary_emails")
    primary_phones = Table("user_phone_numbers").as_("primary_phones")
    claim_emails = Table("user_email_addresses").as_("claim_emails")
    claim_phones = Table("user_phone_numbers").as_("claim_phones")

    query = (
        Query.from_(users)
        .select(
            ExistsCriterion(
                Query.from_(user_journeys)
                .select(1)
                .where(user_journeys.user_id == users.id)
            ).as_("b1"),
            users.given_name,
            users.family_name,
            primary_emails.email,
            primary_emails.verified,
            primary_phones.phone_number,
            primary_phones.verified,
        )
        .left_outer_join(primary_emails)
        .on(primary_email_join_clause(users=users, user_email_addresses=primary_emails))
        .left_outer_join(primary_phones)
        .on(primary_phone_join_clause(users=users, user_phone_numbers=primary_phones))
        .where(users.sub == Parameter("?"))
    )
    qargs = []

    if interpreted_claims.email is not None and not interpreted_claims.email_verified:
        query = query.select(claim_emails.verified)
        query = query.left_outer_join(claim_emails).on(
            (claim_emails.user_id == users.id) & (claim_emails.email == Parameter("?"))
        )
        qargs.append(interpreted_claims.email)

    if (
        interpreted_claims.phone_number is not None
        and not interpreted_claims.phone_number_verified
    ):
        query = query.select(claim_phones.verified)
        query = query.left_outer_join(claim_phones).on(
            (claim_phones.user_id == users.id)
            & (claim_phones.phone_number == Parameter("?"))
        )
        qargs.append(interpreted_claims.phone_number)

    qargs.append(user.user_sub)

    response = await cursor.execute(
        query.get_sql(),
        qargs,
    )

    if not response.results:
        # raced with the create almost certainly, which means we can make a pretty good
        # assumption about this users state
        onboard = True
        given_name = None
        family_name = None
        email = None
        email_verified = False
        phone_number = None
        phone_number_verified = False
        name = None
        claim_email_verified = False
        claim_phone_verified = False
    else:
        onboard: bool = not response.results[0][0]
        given_name: Optional[str] = response.results[0][1]
        family_name: Optional[str] = response.results[0][2]
        email: Optional[str] = response.results[0][3]
        email_verified: bool = bool(response.results[0][4])
        phone_number: Optional[str] = response.results[0][5]
        phone_number_verified: bool = bool(response.results[0][6])
        name = (
            f"{given_name} {family_name}"
            if given_name is not None and family_name is not None
            else None
        )
        idx = 7
        claim_email_verified = False
        if (
            interpreted_claims.email is not None
            and not interpreted_claims.email_verified
        ):
            claim_email_verified = bool(response.results[0][idx])
            idx += 1

        claim_phone_verified = False
        if (
            interpreted_claims.phone_number is not None
            and not interpreted_claims.phone_number_verified
        ):
            claim_phone_verified = bool(response.results[0][idx])
            idx += 1

    jwt_email, jwt_email_verified = select_best_current_email(
        interpreted_claims.email,
        interpreted_claims.email_verified or claim_email_verified,
        email,
        email_verified,
    )
    jwt_phone, jwt_phone_verified = select_best_current_phone(
        interpreted_claims.phone_number,
        interpreted_claims.phone_number_verified or claim_phone_verified,
        phone_number,
        phone_number_verified,
    )

    user_context_claims = {
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

    now = int(time.time())
    feature_flags: Optional[List[str]] = None
    if os.environ["ENVIRONMENT"] == "dev":
        feature_flags = []
        feature_flags.append("series")
    else:
        if (
            jwt_email is not None
            and jwt_email.endswith("@oseh.com")
            and jwt_email_verified
        ):
            feature_flags = []
            feature_flags.append("series")

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
            **user_context_claims,
            **({} if feature_flags is None else {"oseh:feature_flags": feature_flags}),
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
                **user_context_claims,
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
    email = claims.get("email")
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

    for _ in range(5):
        user = await _try_login_existing_account_with_identity(
            itgs,
            provider=provider,
            interpreted_claims=interpreted_claims,
            example_claims=example_claims,
            now=time.time(),
        )
        if user is not None:
            return user
        user = await _try_create_new_account_with_identity(
            itgs,
            provider=provider,
            interpreted_claims=interpreted_claims,
            example_claims=example_claims,
            now=time.time(),
        )
        if user is not None and os.environ["ENVIRONMENT"] != "dev":
            await enqueue_send_described_user_slack_message(
                itgs,
                message=f"{{name}} just signed up with {provider}!",
                sub=user.user_sub,
                channel="oseh_bot",
            )
            return user
        await asyncio.sleep(0.1 + 0.1 * random.random())

    raise OauthInternalException(
        "Failed to initialize user - too many concurrent modifications"
    )


async def _try_login_existing_account_with_identity(
    itgs: Itgs,
    *,
    provider: str,
    interpreted_claims: InterpretedClaims,
    example_claims: dict,
    now: float,
) -> Optional[UserWithIdentity]:
    """Attempts to find and update the user associated with the identity
    described by the given provider and claims, returning their sub and the uid
    of the corresponding user<->identity relationship. If the user cannot be found, returns None.

    This always occurs at the equivalent to strong read consistency.

    This races between checking and performing side effects; if the account is
    deleted between the two checks, no side effects occur but the user is
    returned. A warning is emitted in this case.

    Has the following side effects (outside of the above race):

    - If the interpreted claims indicate an email address, it will be
      associated with the user.
    - If the email address already associated, if the claims indicate a verified
      email address and the association does not indicate it is verified, it is
      flagged verified.
    - If the interpreted claims indicate a phone number, it will be associated
      with the user.
    - If the phone number already associated, if the claims indicate a verified
      phone number and the association does not indicate it is verified, it is
      flagged verified.
    - The example claims on the user<->identity relationship will be updated
    - The last seen timestamp on the user<->identity relationship will be updated
    - If the interpreted claims indicate a profile picture a job will be queued
      to process the new picture and the `users:{user_sub}:checking_profile_image`
      key will be set so that `users.me.routes.picture` will return a hint to the
      client that the image might still be processing for a short while, causing
      the client to retry the request later.

    Args:
        itgs (Itgs): the integrations to (re)use
        provider (str): the provider for the identity used, e.g., SignInWithApple
        interpreted_claims (InterpretedClaims): the claims we got back from the
            provider when we provided them the oauth code. These are the only claims
            that impact our behavior. This might contain almost nothing, especially
            common for SignInWithApple.
        example_claims (dict): the example claims from the provider, which are stored
            for debugging purposes. These do not impact our behavior.
        now (float): Canonical current time, in seconds since the epoch
    """
    conn = await itgs.conn()
    cursor = conn.cursor("strong")

    response = await cursor.execute(
        "SELECT"
        " users.sub,"
        " user_identities.uid "
        "FROM users, user_identities "
        "WHERE"
        " users.id = user_identities.user_id"
        " AND user_identities.provider = ?"
        " AND user_identities.sub = ?",
        [provider, interpreted_claims.sub],
    )
    if not response.results:
        return None

    result = UserWithIdentity(
        user_sub=response.results[0][0],
        identity_uid=response.results[0][1],
    )

    # Get the profile picture processing started as early as possible
    if interpreted_claims.picture is not None:
        redis = await itgs.redis()
        async with redis.pipeline() as pipe:
            pipe.multi()
            await pipe.set(
                f"users:{result.user_sub}:checking_profile_image".encode("utf-8"),
                1,
                ex=10,
            )
            await pipe.rpush(
                b"jobs:hot",  # type: ignore
                json.dumps(
                    {
                        "name": "runners.check_profile_picture",
                        "kwargs": {
                            "user_sub": result.user_sub,
                            "picture_url": interpreted_claims.picture,
                            "jwt_iat": interpreted_claims.iat,
                        },
                        "queued_at": time.time(),
                    }
                ).encode("utf-8"),
            )
            await pipe.execute()

    # We're uploading quite a script here! But all done in a single
    # Raft transaction, so surprisingly little overhead
    queries: List[_LoginQuery] = [
        _update_last_seen(result, example_claims, now),
        *_update_email(result, provider, interpreted_claims, now),
        *_update_phone(result, provider, interpreted_claims, now),
    ]

    query_result = await cursor.executemany3([(q.query, q.qargs) for q in queries])
    async with contact_method_stats(itgs) as stats:
        for query, item in zip(queries, query_result):
            await query.response_handler(itgs, item, stats)
    return result


@dataclass
class _LoginQuery:
    query: str
    qargs: Union[list, tuple]
    response_handler: Callable[
        [Itgs, ResultItem, ContactMethodStatsPreparer], Awaitable[None]
    ]


def _update_last_seen(
    result: UserWithIdentity, example_claims: dict, now: float
) -> _LoginQuery:
    def slack_context() -> str:
        return (
            f"\n\n```\result={clean_for_slack(repr(result))}\n```\n\n"
            f"```\nexample_claims={clean_for_slack(repr(example_claims))}\n```\n\n"
        )

    async def handler(itgs: Itgs, item: ResultItem, stats: ContactMethodStatsPreparer):
        if item.rows_affected != 1:
            await handle_warning(
                f"{__name__}:last_seen:odd_rows_affected",
                f"Expected 1 row affected, got {item.rows_affected}{slack_context()}",
            )

    return _LoginQuery(
        query="UPDATE user_identities SET example_claims=?, last_seen_at=? WHERE uid=?",
        qargs=(
            json.dumps(example_claims, sort_keys=True),
            now,
            result.identity_uid,
        ),
        response_handler=handler,
    )


def _make_update_contact_method_handler(
    user: UserWithIdentity,
    provider: str,
    interpreted_claims: InterpretedClaims,
    now: float,
    *,
    channel: Literal["email", "phone"],
    claim_is_verified: bool,
    enabled_initially: bool,
):
    associated = None
    logged_verify = None
    unix_date = unix_dates.unix_timestamp_to_unix_date(now, tz=tz)

    def slack_context() -> str:
        return (
            f"\n\n```\nuser={clean_for_slack(repr(user))}\n```\n\n"
            f"```\nprovider={clean_for_slack(repr(provider))}\n```\n\n"
            f"```\ninterpreted_claims={clean_for_slack(repr(interpreted_claims))}\n```"
        )

    async def handler(
        id: str, itgs: Itgs, item: ResultItem, stats: ContactMethodStatsPreparer
    ):
        nonlocal associated
        nonlocal logged_verify

        if id == "associate":
            associated = item.rows_affected is not None and item.rows_affected > 0
            if associated and item.rows_affected != 1:
                await handle_warning(
                    f"{__name__}:{channel}:associate:multiple_rows_affected",
                    f"Expected 1 row affected, got {item.rows_affected}{slack_context()}",
                )
            if associated:
                stats.incr_created(
                    unix_date,
                    channel=channel,
                    verified=claim_is_verified,
                    enabled=enabled_initially,
                    reason="identity",
                )
        elif id == "log_associate":
            assert associated is not None, "log_associate called before associate"

            logged_associate = item.rows_affected is not None and item.rows_affected > 0
            if logged_associate and item.rows_affected != 1:
                await handle_warning(
                    f"{__name__}:{channel}:log_associate:multiple_rows_affected",
                    f"Expected 1 row affected, got {item.rows_affected}{slack_context()}",
                )

            if logged_associate is not associated:
                await handle_warning(
                    f"{__name__}:{channel}:associate:mismatch",
                    f"Expected `{logged_associate=}` to match `{associated=}`{slack_context()}",
                )
        elif id == "log_verify":
            assert associated is not None, "log_verify called before associate"
            assert (
                claim_is_verified is True
            ), "log_verify called but claim_is_verified is not True"
            logged_verify = item.rows_affected is not None and item.rows_affected > 0
            if logged_verify and item.rows_affected != 1:
                await handle_warning(
                    f"{__name__}:{channel}:log_verify:multiple_rows_affected",
                    f"Expected 1 row affected, got {item.rows_affected}{slack_context()}",
                )

            if associated and logged_verify:
                await handle_warning(
                    f"{__name__}:{channel}:log_verify:associated_and_logged_verify",
                    f"It does not make sense to associate and verify for the same transaction{slack_context()}",
                )
        elif id == "verify":
            assert logged_verify is not None, "verify called before log_verify"
            verified = item.rows_affected is not None and item.rows_affected > 0
            if verified and item.rows_affected != 1:
                await handle_warning(
                    f"{__name__}:{channel}:verify:multiple_rows_affected",
                    f"Expected 1 row affected, got {item.rows_affected}{slack_context()}",
                )

            if logged_verify is not verified:
                await handle_warning(
                    f"{__name__}:{channel}:verify:mismatch",
                    f"Expected `{logged_verify=}` to match `{verified=}`{slack_context()}",
                )

            if verified:
                stats.incr_verified(unix_date, channel=channel, reason="identity")
        elif id == "add_reminders":
            added = item.rows_affected is not None and item.rows_affected > 0
            if added and item.rows_affected != 1:
                await handle_warning(
                    f"{__name__}:{channel}:add_reminders:multiple_rows_affected",
                    f"Expected 1 row affected, got {item.rows_affected}{slack_context()}",
                )

            if not associated and not logged_verify and added:
                await handle_warning(
                    f"{__name__}:{channel}:add_reminders:mismatch",
                    f"Registered for reminders but neither `{associated=}` nor `{logged_verify=}`{slack_context()}",
                )

            if added:
                logger.info(
                    f"Registered {user.user_sub} for daily reminders on {channel}"
                )

                drr_stats = DailyReminderRegistrationStatsPreparer()
                drr_stats.incr_subscribed(
                    unix_date,
                    channel="sms" if channel == "phone" else channel,
                    reason="email_added",
                )
                stats.stats.merge_with(drr_stats)
        else:
            assert False, id

    return handler


def _update_email(
    user: UserWithIdentity,
    provider: str,
    interpreted_claims: InterpretedClaims,
    now: float,
) -> List[_LoginQuery]:
    if interpreted_claims.email is None:
        return []

    handler = _make_update_contact_method_handler(
        user,
        provider,
        interpreted_claims,
        now,
        channel="email",
        claim_is_verified=not not interpreted_claims.email_verified,
        enabled_initially=True,
    )

    insert_cml_uid = f"oseh_cml_{secrets.token_urlsafe(16)}"
    new_uea_uid = f"oseh_uea_{secrets.token_urlsafe(16)}"
    verify_cml_uid = f"oseh_cml_{secrets.token_urlsafe(16)}"
    daily_reminders_uid = f"oseh_udr_{secrets.token_urlsafe(16)}"
    contact_method_log_reason = json.dumps(
        {
            "repo": "backend",
            "file": __name__,
            "reason": "initialize_user_from_info login",
            "context": {
                "identity_uid": user.identity_uid,
                "provider": provider,
                "sub": interpreted_claims.sub,
            },
        }
    )
    return [
        # associate
        _LoginQuery(
            query=(
                "INSERT INTO user_email_addresses ("
                " uid, user_id, email, verified, receives_notifications, created_at"
                ") SELECT"
                " ?, users.id, ?, ?, ?, ? "
                "FROM users "
                "WHERE"
                " users.sub = ?"
                " AND NOT EXISTS ("
                "  SELECT 1 FROM user_email_addresses AS uea"
                "  WHERE uea.user_id = users.id AND uea.email = ? COLLATE NOCASE"
                " )"
            ),
            qargs=[
                new_uea_uid,
                interpreted_claims.email,
                int(not not interpreted_claims.email_verified),
                True,
                now,
                user.user_sub,
                interpreted_claims.email,
            ],
            response_handler=partial(handler, "associate"),
        ),
        # log_associate
        _LoginQuery(
            query=(
                "INSERT INTO contact_method_log ("
                " uid, user_id, channel, identifier, action, reason, created_at"
                ") SELECT"
                " ?, users.id, ?, ?, ?, ?, ? "
                "FROM users "
                "WHERE"
                " users.sub = ?"
                " AND EXISTS (SELECT 1 FROM user_email_addresses WHERE user_email_addresses.uid = ?)"
            ),
            qargs=[
                insert_cml_uid,
                "email",
                interpreted_claims.email,
                (
                    "create_verified"
                    if interpreted_claims.email_verified
                    else "create_unverified"
                ),
                contact_method_log_reason,
                now,
                user.user_sub,
                new_uea_uid,
            ],
            response_handler=partial(handler, "log_associate"),
        ),
        # log_verify, verify, add_reminders
        *(
            []
            if not interpreted_claims.email_verified
            else [
                # log_verify
                _LoginQuery(
                    query=(
                        "INSERT INTO contact_method_log ("
                        " uid, user_id, channel, identifier, action, reason, created_at"
                        ") SELECT"
                        " ?, users.id, ?, ?, ?, ?, ? "
                        "FROM users "
                        "WHERE"
                        " users.sub = ?"
                        " AND EXISTS ("
                        "  SELECT 1 FROM user_email_addresses AS uea"
                        "  WHERE"
                        "   uea.user_id = users.id"
                        "   AND uea.email = ? COLLATE NOCASE"
                        "   AND uea.uid <> ?"
                        "   AND uea.verified = 0"
                        " )"
                    ),
                    qargs=[
                        verify_cml_uid,
                        "email",
                        interpreted_claims.email,
                        "verify",
                        contact_method_log_reason,
                        now,
                        user.user_sub,
                        interpreted_claims.email,
                        new_uea_uid,
                    ],
                    response_handler=partial(handler, "log_verify"),
                ),
                # verify
                _LoginQuery(
                    query=(
                        "UPDATE user_email_addresses SET verified = 1 "
                        "WHERE"
                        " user_email_addresses.email = ? COLLATE NOCASE"
                        " AND user_email_addresses.uid <> ?"
                        " AND user_email_addresses.verified = 0"
                        " AND EXISTS ("
                        "SELECT 1 FROM users "
                        "WHERE"
                        " users.sub = ?"
                        " AND users.id = user_email_addresses.user_id"
                        ")"
                    ),
                    qargs=[
                        interpreted_claims.email,
                        new_uea_uid,
                        user.user_sub,
                    ],
                    response_handler=partial(handler, "verify"),
                ),
                # add_reminders
                _LoginQuery(
                    query=(
                        "INSERT INTO user_daily_reminders ("
                        " uid, user_id, channel, start_time, end_time, day_of_week_mask, created_at"
                        ") "
                        "SELECT"
                        " ?,"
                        " users.id,"
                        " 'email',"
                        " CASE"
                        "  WHEN settings.id IS NULL THEN 21600"
                        "  WHEN json_extract(settings.time_range, '$.type') = 'preset' THEN"
                        "   CASE json_extract(settings.time_range, '$.preset')"
                        "    WHEN 'afternoon' THEN 46800"
                        "    WHEN 'evening' THEN 61200"
                        "    ELSE 21600"
                        "   END"
                        "  WHEN json_extract(settings.time_range, '$.type') = 'explicit' THEN"
                        "   json_extract(settings.time_range, '$.start')"
                        "  ELSE 21600"
                        " END,"
                        " CASE"
                        "  WHEN settings.id IS NULL THEN 39600"
                        "  WHEN json_extract(settings.time_range, '$.type') = 'preset' THEN"
                        "   CASE json_extract(settings.time_range, '$.preset')"
                        "    WHEN 'afternoon' THEN 57600"
                        "    WHEN 'evening' THEN 68400"
                        "    ELSE 39600"
                        "   END"
                        "  WHEN json_extract(settings.time_range, '$.type') = 'explicit' THEN"
                        "   json_extract(settings.time_range, '$.end')"
                        "  ELSE 39600"
                        " END,"
                        " COALESCE(settings.day_of_week_mask, 127),"
                        " ? "
                        "FROM users "
                        "LEFT OUTER JOIN user_daily_reminder_settings AS settings "
                        "ON settings.id = ("
                        " SELECT s.id FROM user_daily_reminder_settings AS s"
                        " WHERE"
                        "  s.user_id = users.id"
                        "  AND (s.channel = 'email' OR s.day_of_week_mask <> 0)"
                        " ORDER BY"
                        "  s.channel = 'email' DESC,"
                        "  CASE json_extract(s.time_range, '$.type')"
                        "   WHEN 'explicit' THEN 0"
                        "   WHEN 'preset' THEN 1"
                        "   ELSE 2"
                        "  END ASC,"
                        "  (s.day_of_week_mask & 1 > 0) + (s.day_of_week_mask & 2 > 0) + (s.day_of_week_mask & 4 > 0) + (s.day_of_week_mask & 8 > 0) + (s.day_of_week_mask & 16 > 0) + (s.day_of_week_mask & 32 > 0) + (s.day_of_week_mask & 64 > 0) ASC,"
                        "  CASE s.channel"
                        "   WHEN 'email' THEN 0"
                        "   WHEN 'sms' THEN 1"
                        "   WHEN 'push' THEN 2"
                        "   ELSE 3"
                        "  END ASC"
                        "  LIMIT 1"
                        ") "
                        "WHERE"
                        " users.sub = ?"
                        " AND NOT EXISTS ("
                        "  SELECT 1 FROM user_daily_reminders AS udr"
                        "  WHERE"
                        "   udr.user_id = users.id"
                        "   AND udr.channel = 'email'"
                        " )"
                        " AND (settings.day_of_week_mask IS NULL OR settings.day_of_week_mask <> 0)"
                        " AND NOT EXISTS ("
                        "  SELECT 1 FROM suppressed_emails"
                        "  WHERE suppressed_emails.email_address = ? COLLATE NOCASE"
                        " )"
                    ),
                    qargs=[
                        daily_reminders_uid,
                        now,
                        user.user_sub,
                        interpreted_claims.email,
                    ],
                    response_handler=partial(handler, "add_reminders"),
                ),
            ]
        ),
    ]


def _update_phone(
    user: UserWithIdentity,
    provider: str,
    interpreted_claims: InterpretedClaims,
    now: float,
) -> List[_LoginQuery]:
    if interpreted_claims.phone_number is None:
        return []

    handler = _make_update_contact_method_handler(
        user,
        provider,
        interpreted_claims,
        now,
        channel="phone",
        claim_is_verified=not not interpreted_claims.phone_number_verified,
        enabled_initially=False,
    )

    insert_cml_uid = f"oseh_cml_{secrets.token_urlsafe(16)}"
    new_upn_uid = f"oseh_upn_{secrets.token_urlsafe(16)}"
    verify_cml_uid = f"oseh_cml_{secrets.token_urlsafe(16)}"
    contact_method_log_reason = json.dumps(
        {
            "repo": "backend",
            "file": __name__,
            "reason": "initialize_user_from_info login",
            "context": {
                "identity_uid": user.identity_uid,
                "provider": provider,
                "sub": interpreted_claims.sub,
            },
        }
    )
    return [
        # associate
        _LoginQuery(
            query=(
                "INSERT INTO user_phone_numbers ("
                " uid, user_id, phone_number, verified, receives_notifications, created_at"
                ") SELECT"
                " ?, users.id, ?, ?, ?, ? "
                "FROM users "
                "WHERE"
                " users.sub = ?"
                " AND NOT EXISTS ("
                "  SELECT 1 FROM user_phone_numbers AS upn"
                "  WHERE upn.user_id = users.id AND upn.phone_number = ?"
                " )"
            ),
            qargs=[
                new_upn_uid,
                interpreted_claims.phone_number,
                int(not not interpreted_claims.phone_number_verified),
                False,
                now,
                user.user_sub,
                interpreted_claims.phone_number,
            ],
            response_handler=partial(handler, "associate"),
        ),
        # log_associate
        _LoginQuery(
            query=(
                "INSERT INTO contact_method_log ("
                " uid, user_id, channel, identifier, action, reason, created_at"
                ") SELECT"
                " ?, users.id, ?, ?, ?, ?, ? "
                "FROM users "
                "WHERE"
                " users.sub = ?"
                " AND EXISTS (SELECT 1 FROM user_phone_numbers WHERE user_phone_numbers.uid = ?)"
            ),
            qargs=[
                insert_cml_uid,
                "phone",
                interpreted_claims.phone_number,
                (
                    "create_verified"
                    if interpreted_claims.phone_number_verified
                    else "create_unverified"
                ),
                contact_method_log_reason,
                now,
                user.user_sub,
                new_upn_uid,
            ],
            response_handler=partial(handler, "log_associate"),
        ),
        # log_verify, verify
        *(
            []
            if not interpreted_claims.phone_number_verified
            else [
                # log_verify
                _LoginQuery(
                    query=(
                        "INSERT INTO contact_method_log ("
                        " uid, user_id, channel, identifier, action, reason, created_at"
                        ") SELECT"
                        " ?, users.id, ?, ?, ?, ?, ? "
                        "FROM users "
                        "WHERE"
                        " users.sub = ?"
                        " AND EXISTS ("
                        "  SELECT 1 FROM user_phone_numbers AS upn"
                        "  WHERE"
                        "   upn.user_id = users.id"
                        "   AND upn.phone_number = ?"
                        "   AND upn.uid <> ?"
                        "   AND upn.verified = 0"
                        " )"
                    ),
                    qargs=[
                        verify_cml_uid,
                        "phone",
                        interpreted_claims.phone_number,
                        "verify",
                        contact_method_log_reason,
                        now,
                        user.user_sub,
                        interpreted_claims.phone_number,
                        new_upn_uid,
                    ],
                    response_handler=partial(handler, "log_verify"),
                ),
                # verify
                _LoginQuery(
                    query=(
                        "UPDATE user_phone_numbers SET verified = 1 "
                        "WHERE"
                        " user_phone_numbers.phone_number = ?"
                        " AND user_phone_numbers.uid <> ?"
                        " AND user_phone_numbers.verified = 0"
                        " AND EXISTS ("
                        "SELECT 1 FROM users "
                        "WHERE"
                        " users.sub = ?"
                        " AND users.id = user_phone_numbers.user_id"
                        ")"
                    ),
                    qargs=[
                        interpreted_claims.phone_number,
                        new_upn_uid,
                        user.user_sub,
                    ],
                    response_handler=partial(handler, "verify"),
                ),
            ]
        ),
    ]


async def _try_create_new_account_with_identity(
    itgs: Itgs,
    *,
    provider: str,
    interpreted_claims: InterpretedClaims,
    example_claims: dict,
    now: float,
) -> Optional[UserWithIdentity]:
    """Attempts to create a new account and associate it with the given identity.
    Does nothing if there is already an account associated with the given identity.

    Has the following effects on success:
    - A row is inserted into the `users` table
    - A row is inserted into the `user_identities` table
    - If the interpreted claims include an email address a row is inserted
      into `user_email_addresses` table (and the associated stats/logs are updated)
    - If the interpreted claims include a verified email address, it may require
      us to insert a row in `user_daily_reminders`
    - If the interpreted claims include a phone number a row is inserted
      into `user_phone_numbers` table (and the associated stats/logs are updated)
    - A job is queued to initialize a revenue cat user for the new user
    - If the interpreted claims include a profile picture, the redis key
      `users:{user_sub}:checking_profile_image` is set so that
      `users.me.routes.picture` will return a hint to the client that the image
      might still be processing for a short while, causing the client to retry
      the request later. Also, a job is queued to process the new picture.
    - The user stats are updated to indicate a new account was created

    Args:
        itgs (Itgs): the integrations to (re)use
        provider (str): the provider for the identity used, e.g., SignInWithApple
        interpreted_claims (InterpretedClaims): the claims we got back from the
            provider when we provided them the oauth code. These are the only claims
            that impact our behavior. This might contain almost nothing, especially
            common for SignInWithApple.
        example_claims (dict): the example claims from the provider, which are stored
            for debugging purposes. These do not impact our behavior.
        now (float): Canonical current time, in seconds since the epoch

    Returns:
        (UserWithIdentity, None): the identifiers for the newly created user/identity,
            or None if there is already a user associated with the given identity
    """
    user_sub = f"oseh_u_{secrets.token_urlsafe(16)}"
    identity_uid = f"oseh_ui_{secrets.token_urlsafe(16)}"

    queries: List[_CreateQuery] = [
        *_insert_user(
            user_sub=user_sub,
            provider=provider,
            interpreted_claims=interpreted_claims,
            now=now,
        ),
        _insert_identity(
            user_sub=user_sub,
            identity_uid=identity_uid,
            provider=provider,
            interpreted_claims=interpreted_claims,
            example_claims=example_claims,
            now=now,
        ),
        *_insert_email(
            user_sub=user_sub,
            identity_uid=identity_uid,
            provider=provider,
            interpreted_claims=interpreted_claims,
            now=now,
        ),
        *_insert_phone(
            user_sub=user_sub,
            identity_uid=identity_uid,
            provider=provider,
            interpreted_claims=interpreted_claims,
            now=now,
        ),
    ]

    conn = await itgs.conn()
    cursor = conn.cursor("strong")
    response = await cursor.executemany3([(q.query, q.qargs) for q in queries])
    created = response[0].rows_affected is not None and response[0].rows_affected > 0

    stats = RedisStatsPreparer()
    for query, item in zip(queries, response):
        await query.response_handler(itgs, item, stats, created)
    await stats.store(itgs)

    if not created:
        return None

    redis = await itgs.redis()
    queued_at = time.time()
    async with redis.pipeline() as pipe:
        pipe.multi()
        await pipe.rpush(
            b"jobs:hot",  # type: ignore
            json.dumps(
                {
                    "name": "runners.revenue_cat.ensure_user",
                    "kwargs": {"user_sub": user_sub},
                    "queued_at": queued_at,
                }
            ).encode("utf-8"),
            *(
                []
                if interpreted_claims.picture is None
                else [
                    json.dumps(
                        {
                            "name": "runners.check_profile_picture",
                            "kwargs": {
                                "user_sub": user_sub,
                                "picture_url": interpreted_claims.picture,
                                "jwt_iat": interpreted_claims.iat,
                            },
                            "queued_at": time.time(),
                        }
                    ).encode("utf-8")
                ]
            ),
        )
        if interpreted_claims.picture is not None:
            await pipe.set(
                f"users:{user_sub}:checking_profile_image".encode("utf-8"),
                1,
                ex=10,
            )
        await pipe.execute()

    return UserWithIdentity(user_sub=user_sub, identity_uid=identity_uid)


@dataclass
class _CreateQuery:
    query: str
    qargs: list
    response_handler: Callable[
        [Itgs, ResultItem, RedisStatsPreparer, bool], Awaitable[None]
    ]


def _insert_user(
    *,
    user_sub: str,
    provider: str,
    interpreted_claims: InterpretedClaims,
    now: float,
) -> Sequence[_CreateQuery]:
    revenue_cat_uid = f"oseh_iurc_{secrets.token_urlsafe(16)}"
    revenue_cat_id = f"oseh_u_rc_{secrets.token_urlsafe(16)}"

    def slack_context():
        return (
            f"\n\n```\nuser_sub={clean_for_slack(repr(user_sub))}\n```\n\n"
            f"```\nprovider={clean_for_slack(repr(provider))}\n```\n\n"
            f"```\ninterpreted_claims={clean_for_slack(repr(interpreted_claims))}\n```",
        )

    async def handler(
        step: Literal["user", "revenue_cat"],
        itgs: Itgs,
        item: ResultItem,
        stats: RedisStatsPreparer,
        created: bool,
    ):
        inserted = item.rows_affected is not None and item.rows_affected > 0
        assert inserted is created, f"{inserted=} is not {created=} for {step=}"
        if inserted and item.rows_affected != 1:
            await handle_warning(
                f"{__name__}:insert_user:multiple_rows_affected:{step}",
                f"Expected 1 row affected, got {item.rows_affected}{slack_context()}",
            )
        if inserted and step == "user":
            await users.lib.stats.on_user_created(itgs, user_sub, now)

    return [
        _CreateQuery(
            query=(
                "INSERT INTO users ("
                " sub, given_name, family_name, admin, timezone, created_at"
                ") SELECT"
                " ?, ?, ?, 0, NULL, ? "
                "WHERE NOT EXISTS ("
                "SELECT 1 FROM user_identities "
                "WHERE user_identities.provider = ? AND user_identities.sub = ?"
                ")"
            ),
            qargs=[
                user_sub,
                interpreted_claims.given_name,
                interpreted_claims.family_name,
                now,
                provider,
                interpreted_claims.sub,
            ],
            response_handler=partial(handler, "user"),
        ),
        _CreateQuery(
            query=(
                "INSERT INTO user_revenue_cat_ids ("
                " uid, user_id, revenue_cat_id, revenue_cat_attributes, created_at, checked_at"
                ") SELECT"
                " ?, users.id, ?, ?, ?, ? "
                "FROM users "
                "WHERE users.sub = ?"
            ),
            qargs=[
                revenue_cat_uid,
                revenue_cat_id,
                "{}",
                now,
                now,
                user_sub,
            ],
            response_handler=partial(handler, "revenue_cat"),
        ),
    ]


def _insert_identity(
    *,
    user_sub: str,
    identity_uid: str,
    provider: str,
    interpreted_claims: InterpretedClaims,
    example_claims: dict,
    now: float,
) -> _CreateQuery:
    def slack_context():
        return (
            f"\n\n```\nuser_sub={clean_for_slack(repr(user_sub))}\n```\n\n"
            f"```\nprovider={clean_for_slack(repr(provider))}\n```\n\n"
            f"```\ninterpreted_claims={clean_for_slack(repr(interpreted_claims))}\n```",
        )

    async def handler(
        itgs: Itgs, item: ResultItem, stats: RedisStatsPreparer, created: bool
    ):
        inserted = item.rows_affected is not None and item.rows_affected > 0
        if inserted and item.rows_affected != 1:
            await handle_warning(
                f"{__name__}:insert_identity:multiple_rows_affected",
                f"Expected 1 row affected, got {item.rows_affected}{slack_context()}",
            )
        if inserted is not created:
            await handle_warning(
                f"{__name__}:insert_identity:mismatch",
                f"Inserted into `users` but not into `user_identities`?{slack_context()}",
            )

    return _CreateQuery(
        query=(
            "INSERT INTO user_identities ("
            " uid, user_id, provider, sub, example_claims, last_seen_at, created_at"
            ") SELECT"
            " ?, users.id, ?, ?, ?, ?, ? "
            "FROM users "
            "WHERE users.sub = ?"
        ),
        qargs=[
            identity_uid,
            provider,
            interpreted_claims.sub,
            json.dumps(example_claims, sort_keys=True),
            now,
            now,
            user_sub,
        ],
        response_handler=handler,
    )


def _insert_email(
    *,
    user_sub: str,
    identity_uid: str,
    provider: str,
    interpreted_claims: InterpretedClaims,
    now: float,
) -> List[_CreateQuery]:
    unix_date = unix_dates.unix_timestamp_to_unix_date(now, tz=tz)

    if interpreted_claims.email is None:
        return []

    def slack_context():
        return (
            f"\n\n```\nuser_sub={clean_for_slack(repr(user_sub))}\n```\n\n"
            f"```\nidentity_uid={clean_for_slack(repr(identity_uid))}\n```\n\n"
            f"```\nprovider={clean_for_slack(repr(provider))}\n```\n\n"
            f"```\ninterpreted_claims={clean_for_slack(repr(interpreted_claims))}\n```",
        )

    async def handler(
        id: str, itgs: Itgs, item: ResultItem, stats: RedisStatsPreparer, created: bool
    ):
        inserted = item.rows_affected is not None and item.rows_affected > 0
        if inserted and item.rows_affected != 1:
            await handle_warning(
                f"{__name__}:insert_email:multiple_rows_affected",
                f"`id={clean_for_slack(id)}` Expected 1 row affected, got {item.rows_affected}{slack_context()}",
            )
        if inserted is not created:
            await handle_warning(
                f"{__name__}:insert_email:mismatch",
                f"`id={clean_for_slack(id)}` For `user_email_addresses`, `{created=}` but `{inserted=}`?{slack_context()}",
            )
        if id == "associate" and created:
            ContactMethodStatsPreparer(stats).incr_created(
                unix_date,
                channel="email",
                verified=not not interpreted_claims.email_verified,
                enabled=True,
                reason="identity",
            )
        if id == "reminders" and created:
            stats.merge_with(
                DailyReminderRegistrationStatsPreparer().incr_subscribed(
                    unix_date, channel="email", reason="account_created"
                )
            )

    insert_cml_uid = f"oseh_cml_{secrets.token_urlsafe(16)}"
    new_uea_uid = f"oseh_uea_{secrets.token_urlsafe(16)}"
    new_udr_uid = f"oseh_udr_{secrets.token_urlsafe(16)}"
    return [
        # associate
        _CreateQuery(
            query=(
                "INSERT INTO user_email_addresses ("
                " uid, user_id, email, verified, receives_notifications, created_at"
                ") SELECT"
                " ?, users.id, ?, ?, ?, ? "
                "FROM users WHERE users.sub=?"
            ),
            qargs=[
                new_uea_uid,
                interpreted_claims.email,
                int(not not interpreted_claims.email_verified),
                True,
                now,
                user_sub,
            ],
            response_handler=partial(handler, "associate"),
        ),
        # log
        _CreateQuery(
            query=(
                "INSERT INTO contact_method_log ("
                " uid, user_id, channel, identifier, action, reason, created_at"
                ") SELECT"
                " ?, users.id, ?, ?, ?, ?, ? "
                "FROM users WHERE sub=?"
            ),
            qargs=[
                insert_cml_uid,
                "email",
                interpreted_claims.email,
                (
                    "create_verified"
                    if interpreted_claims.email_verified
                    else "create_unverified"
                ),
                json.dumps(
                    {
                        "repo": "backend",
                        "file": __name__,
                        "reason": "initialize_user_from_info create",
                        "context": {
                            "identity_uid": identity_uid,
                            "provider": provider,
                            "sub": interpreted_claims.sub,
                        },
                    }
                ),
                now,
                user_sub,
            ],
            response_handler=partial(handler, "log"),
        ),
        # reminders
        *(
            []
            if not interpreted_claims.email_verified
            else [
                _CreateQuery(
                    query=(
                        "INSERT INTO user_daily_reminders ("
                        " uid, user_id, channel, start_time, end_time, day_of_week_mask, created_at"
                        ") SELECT"
                        " ?, users.id, 'email', 21600, 39600, 127, ? "
                        "FROM users WHERE sub=?"
                    ),
                    qargs=[new_udr_uid, now, user_sub],
                    response_handler=partial(handler, "reminders"),
                )
            ]
        ),
    ]


def _insert_phone(
    *,
    user_sub: str,
    identity_uid: str,
    provider: str,
    interpreted_claims: InterpretedClaims,
    now: float,
) -> List[_CreateQuery]:
    if interpreted_claims.phone_number is None:
        return []

    def slack_context():
        return (
            f"\n\n```\nuser_sub={clean_for_slack(repr(user_sub))}\n```\n\n"
            f"```\nidentity_uid={clean_for_slack(repr(identity_uid))}\n```\n\n"
            f"```\nprovider={clean_for_slack(repr(provider))}\n```\n\n"
            f"```\ninterpreted_claims={clean_for_slack(repr(interpreted_claims))}\n```",
        )

    async def handler(
        id: str, itgs: Itgs, item: ResultItem, stats: RedisStatsPreparer, created: bool
    ):
        inserted = item.rows_affected is not None and item.rows_affected > 0
        if inserted and item.rows_affected != 1:
            await handle_warning(
                f"{__name__}:insert_phone:multiple_rows_affected",
                f"`id={clean_for_slack(id)}` Expected 1 row affected, got {item.rows_affected}{slack_context()}",
            )
        if inserted is not created:
            await handle_warning(
                f"{__name__}:insert_phone:mismatch",
                f"`id={clean_for_slack(id)}` For `user_phone_numbers`, `{created=}` but `{inserted=}`?{slack_context()}",
            )
        if id == "associate" and created:
            ContactMethodStatsPreparer(stats).incr_created(
                unix_dates.unix_timestamp_to_unix_date(now, tz=tz),
                channel="phone",
                verified=not not interpreted_claims.phone_number_verified,
                enabled=False,
                reason="identity",
            )

    insert_cml_uid = f"oseh_cml_{secrets.token_urlsafe(16)}"
    new_uea_uid = f"oseh_uea_{secrets.token_urlsafe(16)}"
    return [
        # associate
        _CreateQuery(
            query=(
                "INSERT INTO user_phone_numbers ("
                " uid, user_id, phone_number, verified, receives_notifications, created_at"
                ") SELECT"
                " ?, users.id, ?, ?, ?, ? "
                "FROM users WHERE users.sub=?"
            ),
            qargs=[
                new_uea_uid,
                interpreted_claims.phone_number,
                int(not not interpreted_claims.phone_number_verified),
                False,
                now,
                user_sub,
            ],
            response_handler=partial(handler, "associate"),
        ),
        # log
        _CreateQuery(
            query=(
                "INSERT INTO contact_method_log ("
                " uid, user_id, channel, identifier, action, reason, created_at"
                ") SELECT"
                " ?, users.id, ?, ?, ?, ?, ? "
                "FROM users WHERE sub=?"
            ),
            qargs=[
                insert_cml_uid,
                "phone",
                interpreted_claims.phone_number,
                (
                    "create_verified"
                    if interpreted_claims.phone_number_verified
                    else "create_unverified"
                ),
                json.dumps(
                    {
                        "repo": "backend",
                        "file": __name__,
                        "reason": "initialize_user_from_info create",
                        "context": {
                            "identity_uid": identity_uid,
                            "provider": provider,
                            "sub": interpreted_claims.sub,
                        },
                    }
                ),
                now,
                user_sub,
            ],
            response_handler=partial(handler, "log"),
        ),
    ]


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
    redis.call("EXPIREAT", key, math.ceil(tonumber(highest_score)))
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
        await redis.evalsha(*evalsha_args)  # type: ignore
    except NoScriptError:
        true_hash = await redis.script_load(
            SORTED_SET_INSERT_WITH_MAX_LENGTH_AND_MIN_SCORE_SCRIPT
        )
        if true_hash != SORTED_SET_INSERT_WITH_MAX_LENGTH_AND_MIN_SCORE_SCRIPT_SHA:
            raise Exception(
                f"sorted set insert script hash mismatch: {true_hash=} != {SORTED_SET_INSERT_WITH_MAX_LENGTH_AND_MIN_SCORE_SCRIPT_SHA=}"
            )

        await redis.evalsha(*evalsha_args)  # type: ignore
