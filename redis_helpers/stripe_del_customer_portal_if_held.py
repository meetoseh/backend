from typing import Any, Literal, Optional, List, Union
import hashlib
import time
import redis.asyncio.client
from pydantic import BaseModel, Field
from itgs import Itgs
from redis_helpers.run_with_prep import run_with_prep

from redis_helpers.stripe_lock_or_retrieve_customer_portal import (
    StripeCustomerPortalState,
    stripe_customer_portal_state_adapter,
)

STRIPE_DEL_CUSTOMER_PORTAL_IF_HELD_LUA_SCRIPT = """
local key = KEYS[1]
local request_id = ARGV[1]

local current_value = redis.call("GET", key)
if current_value == false then
    return {-1, false}
end

local parsed = cjson.decode(current_value)
if parsed.type ~= "loading" or parsed.id ~= request_id then
    return {-2, current_value}
end

redis.call("DEL", key)
return {1, false}
"""

STRIPE_DEL_CUSTOMER_PORTAL_IF_HELD_LUA_SCRIPT_HASH = hashlib.sha1(
    STRIPE_DEL_CUSTOMER_PORTAL_IF_HELD_LUA_SCRIPT.encode("utf-8")
).hexdigest()


_last_stripe_del_customer_portal_if_held_ensured_at: Optional[float] = None


async def ensure_stripe_del_customer_portal_if_held_script_exists(
    redis: redis.asyncio.client.Redis, *, force: bool = False
) -> None:
    """Ensures the stripe_del_customer_portal_if_held lua script is loaded into redis."""
    global _last_stripe_del_customer_portal_if_held_ensured_at

    now = time.time()
    if (
        not force
        and _last_stripe_del_customer_portal_if_held_ensured_at is not None
        and (now - _last_stripe_del_customer_portal_if_held_ensured_at < 5)
    ):
        return

    loaded: List[bool] = await redis.script_exists(
        STRIPE_DEL_CUSTOMER_PORTAL_IF_HELD_LUA_SCRIPT_HASH
    )
    if not loaded[0]:
        correct_hash = await redis.script_load(
            STRIPE_DEL_CUSTOMER_PORTAL_IF_HELD_LUA_SCRIPT
        )
        assert (
            correct_hash == STRIPE_DEL_CUSTOMER_PORTAL_IF_HELD_LUA_SCRIPT_HASH
        ), f"{correct_hash=} != {STRIPE_DEL_CUSTOMER_PORTAL_IF_HELD_LUA_SCRIPT_HASH=}"

    if (
        _last_stripe_del_customer_portal_if_held_ensured_at is None
        or _last_stripe_del_customer_portal_if_held_ensured_at < now
    ):
        _last_stripe_del_customer_portal_if_held_ensured_at = now


class StripeDelCustomerPortalResultGone(BaseModel):
    type: Literal["gone"] = Field()
    """Indicates that the requested key was already deleted"""


class StripeDelCustomerPortalResultNotHeld(BaseModel):
    type: Literal["not-held"] = Field()
    """Indicates that the requested key was not held by a lock with the given id"""

    current_value: StripeCustomerPortalState = Field()
    """The current value in the key"""


class StripeDelCustomerPortalResultSuccess(BaseModel):
    type: Literal["success"] = Field()
    """Indicates the key existed and was deleted"""


StripeDelCustomerPortalResult = Union[
    StripeDelCustomerPortalResultGone,
    StripeDelCustomerPortalResultNotHeld,
    StripeDelCustomerPortalResultSuccess,
]


async def stripe_del_customer_portal_if_held(
    redis: redis.asyncio.client.Redis, key: bytes, request_id: bytes
) -> Optional[StripeDelCustomerPortalResult]:
    """Deletes the given key if it is a string key containing a json
    object with type `loading` and `id` matching `request_id`, otherwise,
    just returns the existing value.

    Args:
        redis (redis.asyncio.client.Redis): The redis client
        key (bytes): The key to update
        request_id (bytes): The lock id to check for

    Returns:
        StripeDelCustomerPortalResult, None: The result of the operation
            if not run in a pipeline, otherwise, None since the result is
            not known until the pipeline is executed.

    Raises:
        NoScriptError: If the script is not loaded into redis
    """
    res = await redis.evalsha(STRIPE_DEL_CUSTOMER_PORTAL_IF_HELD_LUA_SCRIPT_HASH, 1, key, request_id)  # type: ignore
    if res is redis:
        return None
    return parse_stripe_del_customer_portal_result(res)


async def stripe_del_customer_portal_if_held_safe(
    itgs: Itgs, key: bytes, request_id: bytes
) -> StripeDelCustomerPortalResult:
    """Executes the stripe_del_customer_portal_if_held lua script in the main redis
    instance, outside of pipelining, and handling creating the script if it does not
    exist.
    """
    redis = await itgs.redis()

    async def _prepare(force: bool):
        await ensure_stripe_del_customer_portal_if_held_script_exists(
            redis, force=force
        )

    async def _execute():
        return await stripe_del_customer_portal_if_held(redis, key, request_id)

    res = await run_with_prep(_prepare, _execute)
    assert res is not None
    return res


def parse_stripe_del_customer_portal_result(res: Any) -> StripeDelCustomerPortalResult:
    """Parses the response from the stripe_del_customer_portal_if_held lua script"""
    assert isinstance(res, (list, tuple)), res
    assert len(res) == 2, res
    assert isinstance(res[0], int), res

    if res[0] == -1:
        assert res[1] is None, res
        return StripeDelCustomerPortalResultGone(type="gone")
    if res[0] == -2:
        assert isinstance(res[1], bytes), res
        return StripeDelCustomerPortalResultNotHeld(
            type="not-held",
            current_value=stripe_customer_portal_state_adapter.validate_json(res[1]),
        )
    if res[0] == 1:
        assert res[1] is False, res
        return StripeDelCustomerPortalResultSuccess(type="success")

    assert False, res
