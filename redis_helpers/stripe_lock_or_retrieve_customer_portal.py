from typing import Any, Literal, Optional, List, Union
from pydantic import BaseModel, Field, TypeAdapter
import hashlib
import time
import redis.asyncio.client

from itgs import Itgs
from redis_helpers.run_with_prep import run_with_prep

STRIPE_LOCK_OR_RETRIEVE_CUSTOMER_PORTAL_LUA_SCRIPT = """
local key = KEYS[1]
local hostname = ARGV[1]
local now = tonumber(ARGV[2])
local request_id = ARGV[3]

local current_value = redis.call('GET', key)
if current_value == false then
    local lock = cjson.encode({
        type = 'loading',
        hostname = hostname,
        started_at = now,
        id = request_id
    })
    redis.call('SET', key, lock, 'EX', 20)
    return {1, false}
end

return {-1, current_value}
"""

STRIPE_LOCK_OR_RETRIEVE_CUSTOMER_PORTAL_LUA_SCRIPT_HASH = hashlib.sha1(
    STRIPE_LOCK_OR_RETRIEVE_CUSTOMER_PORTAL_LUA_SCRIPT.encode("utf-8")
).hexdigest()


_last_stripe_lock_or_retrieve_customer_portal_ensured_at: Optional[float] = None


async def ensure_stripe_lock_or_retrieve_customer_portal_script_exists(
    redis: redis.asyncio.client.Redis, *, force: bool = False
) -> None:
    """Ensures the stripe_lock_or_retrieve_customer_portal lua script is loaded into redis."""
    global _last_stripe_lock_or_retrieve_customer_portal_ensured_at

    now = time.time()
    if (
        not force
        and _last_stripe_lock_or_retrieve_customer_portal_ensured_at is not None
        and (now - _last_stripe_lock_or_retrieve_customer_portal_ensured_at < 5)
    ):
        return

    loaded: List[bool] = await redis.script_exists(
        STRIPE_LOCK_OR_RETRIEVE_CUSTOMER_PORTAL_LUA_SCRIPT_HASH
    )
    if not loaded[0]:
        correct_hash = await redis.script_load(
            STRIPE_LOCK_OR_RETRIEVE_CUSTOMER_PORTAL_LUA_SCRIPT
        )
        assert (
            correct_hash == STRIPE_LOCK_OR_RETRIEVE_CUSTOMER_PORTAL_LUA_SCRIPT_HASH
        ), f"{correct_hash=} != {STRIPE_LOCK_OR_RETRIEVE_CUSTOMER_PORTAL_LUA_SCRIPT_HASH=}"

    if (
        _last_stripe_lock_or_retrieve_customer_portal_ensured_at is None
        or _last_stripe_lock_or_retrieve_customer_portal_ensured_at < now
    ):
        _last_stripe_lock_or_retrieve_customer_portal_ensured_at = now


class StripeCustomerPortalStateLoading(BaseModel):
    type: Literal["loading"] = Field()
    hostname: str = Field()
    started_at: int = Field()
    id: str = Field()


class StripeCustomerPortalStateUnavailable(BaseModel):
    type: Literal["unavailable"] = Field()
    reason: Literal["no-customer", "multiple-customers"] = Field()
    checked_at: int = Field()


class StripeCustomerPortalStateAvailable(BaseModel):
    type: Literal["available"] = Field()
    url: str = Field()
    checked_at: int = Field()


StripeCustomerPortalState = Union[
    StripeCustomerPortalStateLoading,
    StripeCustomerPortalStateUnavailable,
    StripeCustomerPortalStateAvailable,
]
stripe_customer_portal_state_adapter: TypeAdapter[StripeCustomerPortalState] = (
    TypeAdapter(StripeCustomerPortalState)
)


class StripeLockOrRetrieveCustomerPortalResultSuccess(BaseModel):
    success: Literal[True] = Field()
    current_value: Literal[None] = Field()


class StripeLockOrRetrieveCustomerPortalResultFailed(BaseModel):
    success: Literal[False] = Field()
    current_value: StripeCustomerPortalState = Field()


StripeLockOrRetrieveCustomerPortalResult = Union[
    StripeLockOrRetrieveCustomerPortalResultSuccess,
    StripeLockOrRetrieveCustomerPortalResultFailed,
]


async def stripe_lock_or_retrieve_customer_portal(
    redis: redis.asyncio.client.Redis,
    key: bytes,
    hostname: bytes,
    now: int,
    request_id: bytes,
) -> Optional[StripeLockOrRetrieveCustomerPortalResult]:
    """Attempts to lock the given key which is formatted like
    `stripe:customer_portals:{user_sub}` if it is currently unset,
    otherwise returns the current value.

    Args:
        redis (redis.asyncio.client.Redis): The redis client
        key (bytes): the key to lock
        hostname (bytes): the hostname of the server trying to lock the key
        now (int): the current time in seconds since the epoch
        request_id (bytes): a random unique identifier for debugging purposes

    Returns:
        StripeLockOrRetrieveCustomerPortalResult, None: The result, if known.
            None if executed within a transaction, since the result is not known until the
            transaction is executed.

    Raises:
        NoScriptError: If the script is not loaded into redis
    """
    res = await redis.evalsha(STRIPE_LOCK_OR_RETRIEVE_CUSTOMER_PORTAL_LUA_SCRIPT_HASH, 1, key, hostname, str(now).encode("ascii"), request_id)  # type: ignore
    if res is redis:
        return None
    return parse_stripe_lock_or_retrieve_customer_portal_result(res)


async def stripe_lock_or_retrieve_customer_portal_safe(
    itgs: Itgs,
    key: bytes,
    hostname: bytes,
    now: int,
    request_id: bytes,
) -> StripeLockOrRetrieveCustomerPortalResult:
    """The same as stripe_lock_or_retrieve_customer_portal, but manages ensuring
    the script is available
    """
    redis = await itgs.redis()

    async def _prepare(force: bool):
        await ensure_stripe_lock_or_retrieve_customer_portal_script_exists(
            redis, force=force
        )

    async def _execute():
        return await stripe_lock_or_retrieve_customer_portal(
            redis, key, hostname, now, request_id
        )

    res = await run_with_prep(_prepare, _execute)
    assert res is not None
    return res


def parse_stripe_lock_or_retrieve_customer_portal_result(
    res: Any,
) -> StripeLockOrRetrieveCustomerPortalResult:
    assert isinstance(res, (list, tuple)), res
    assert len(res) == 2, res
    code = res[0]
    current_value = res[1]

    assert isinstance(code, int)
    if code == 1:
        assert current_value is None, res
        return StripeLockOrRetrieveCustomerPortalResultSuccess(
            success=True, current_value=None
        )
    assert code == -1
    assert isinstance(current_value, bytes), res
    current_value_parsed = stripe_customer_portal_state_adapter.validate_json(
        current_value
    )
    return StripeLockOrRetrieveCustomerPortalResultFailed(
        success=False, current_value=current_value_parsed
    )
