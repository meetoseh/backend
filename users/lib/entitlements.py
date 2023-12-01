"""This module handles caching basic entitlement information on users, with the
ability to purge the cache.

This is a two-stage cache: RevenueCat -> redis -> diskcache
"""
import asyncio
import time
from typing import (
    Awaitable,
    Dict,
    List,
    Optional,
    NoReturn as Never,
    cast as typing_cast,
)
import perpetual_pub_sub as pps
from pydantic import BaseModel, Field
from error_middleware import handle_error
from itgs import Itgs
import hashlib
from redis.exceptions import NoScriptError
import secrets
import datetime


class CachedEntitlement(BaseModel):
    """Describes information about an entitlement that is cached, either
    in redis or on disk. The identifier of the entitlement is generally
    clear from context.
    """

    is_active: bool = Field(description="If the user has this entitlement")
    expires_at: Optional[float] = Field(
        description=(
            "if the users entitlement is active, but will expire unless renewed, "
            "the earliest time at which it will expire in seconds since the epoch. This "
            "value may be in the past, but should never be used to determine "
            "whether the entitlement is active - it is only provided for "
            "informational purposes"
        )
    )
    checked_at: float = Field(
        description=(
            "The time that the entitlement was retrieved from the source of truth."
        )
    )


class LocalCachedEntitlements(BaseModel):
    """The format for locally cached entitlements on a given user"""

    entitlements: Dict[str, CachedEntitlement] = Field(
        default_factory=dict, description="The entitlements that are cached locally"
    )


async def get_entitlements_from_source(
    itgs: Itgs, *, user_sub: str, now: float
) -> Optional[LocalCachedEntitlements]:
    """Gets all entitlements that a user has ever had, from the source of
    truth. This information is not particularly slow but depends on revenuecat's
    response times, which we cannot control.

    This does not respect the `revenue_cat_errors` redis key, meaning that it
    will send a request even if we've detected a revenue cat outage, and will
    not report any errors that occur.

    Not generally used directly. Prefer `get_entitlement`

    Args:
        itgs (Itgs): the integrations for networked services
        user_sub (str): the sub of the user whose entitlements we are getting
        now (float): the time the request is being made

    Returns:
        LocalCachedEntitlements: if the users entitlement information was fetched
            successfully, their entitlements, otherwise None
    """
    conn = await itgs.conn()
    cursor = conn.cursor("none")

    query = (
        "SELECT user_revenue_cat_ids.revenue_cat_id "
        "FROM users, user_revenue_cat_ids "
        "WHERE"
        " users.sub = ?"
        " AND users.id = user_revenue_cat_ids.user_id"
    )
    qargs = (user_sub,)

    response = await cursor.execute(query, qargs)
    if not response.results:
        response = await cursor.execute(query, qargs, read_consistency="strong")
        if not response.results:
            return None

    revenue_cat_ids: List[str] = [row[0] for row in response.results]
    rc = await itgs.revenue_cat()

    unjoined: List[LocalCachedEntitlements] = []
    dnow = datetime.datetime.fromtimestamp(now, tz=datetime.timezone.utc)

    for revenue_cat_id in revenue_cat_ids:
        truth = await rc.get_customer_info(
            revenue_cat_id=revenue_cat_id, handle_ratelimits=True
        )
        unjoined.append(
            LocalCachedEntitlements(
                entitlements=dict(
                    (
                        key,
                        CachedEntitlement(
                            is_active=(
                                value.expires_date is None or value.expires_date > dnow
                            ),
                            expires_at=(
                                None
                                if value.expires_date is None
                                else value.expires_date.timestamp()
                            ),
                            checked_at=now,
                        ),
                    )
                    for (key, value) in truth.subscriber.entitlements.items()
                )
            )
        )

    return merge_revenue_cat_user_entitlements(unjoined)


def merge_revenue_cat_user_entitlements(
    arr: List[LocalCachedEntitlements],
) -> LocalCachedEntitlements:
    """Returns the maximally permissive union of the given entitlements."""
    if len(arr) == 1:
        return arr[0]

    result = LocalCachedEntitlements(entitlements={})
    for entitlements in arr:
        for key, value in entitlements.entitlements.items():
            if key not in result.entitlements:
                result.entitlements[key] = value
            else:
                current = result.entitlements[key]
                if current.is_active and not value.is_active:
                    continue
                if not current.is_active and value.is_active:
                    result.entitlements[key] = value
                    continue

                result.entitlements[key] = CachedEntitlement(
                    is_active=current.is_active or value.is_active,
                    expires_at=(
                        None
                        if (current.expires_at is None or value.expires_at is None)
                        else max(current.expires_at, value.expires_at)
                    ),
                    checked_at=min(current.checked_at, value.checked_at),
                )
    return result


async def get_entitlement_from_redis(
    itgs: Itgs, *, user_sub: str, identifier: str
) -> Optional[CachedEntitlement]:
    """Gets the entitlement information with the given identifier for the
    given user from redis, if it's available, otherwise returns None.

    Not generally used directly. Prefer `get_entitlement`

    Args:
        itgs (Itgs): the integrations for networked services
        user_sub (str): the sub of the user whose entitlement we are getting
        identifier (str): the identifier of the entitlement we are getting

    Returns:
        CachedEntitlement: if the entitlement was found in redis for that user,
            the entitlement, otherwise None
    """
    redis = await itgs.redis()

    raw = await typing_cast(
        Awaitable[Optional[bytes]],
        redis.hget(
            f"entitlements:{user_sub}".encode("utf-8"), identifier.encode("utf-8")  # type: ignore
        ),
    )
    if raw is None:
        return None

    return CachedEntitlement.model_validate_json(raw)


async def upsert_entitlements_to_redis(
    itgs: Itgs, *, user_sub: str, entitlements: Dict[str, CachedEntitlement]
) -> None:
    """For each specified entitlement sets or replaces the cached
    entitlement information for the given user and identifier pair in redis.
    If there were entitlements already cached for the user which are not
    specified, they are kept as-is.

    All entitlements for a user are expired together. This operation resets the
    expiry time.

    Not generally used directly. Prefer `get_entitlement`

    Args:
        itgs (Itgs): the integrations for networked services
        user_sub (str): the sub of the user whose entitlement we are setting
        entitlements (Dict[str, CachedEntitlement]): the entitlements to set
    """
    redis = await itgs.redis()

    async with redis.pipeline(transaction=True) as pipe:
        pipe.multi()
        await pipe.hset(
            f"entitlements:{user_sub}".encode("utf-8"),  # type: ignore
            mapping=dict(
                (key, value.__pydantic_serializer__.to_json(value))
                for (key, value) in entitlements.items()
            ),
        )
        await pipe.expire(f"entitlements:{user_sub}", 60 * 60 * 24)
        await pipe.execute()


async def purge_entitlements_from_redis(itgs: Itgs, *, user_sub: str) -> None:
    """Removes any entitlements cached for the given user from redis.

    Prefer `get_entitlement` with `force=True` to calling this directly.

    Args:
        itgs (Itgs): the integrations for networked services
        user_sub (str): the sub of the user whose entitlements we are purging
    """
    redis = await itgs.redis()

    await redis.delete(f"entitlements:{user_sub}")


async def get_entitlements_from_local(
    itgs: Itgs, *, user_sub: str
) -> Optional[LocalCachedEntitlements]:
    """Fetches the entitlements for the given user from local cache, if they
    are available, otherwise returns None.

    Not generally used directly. Prefer `get_entitlement`

    Args:
        itgs (Itgs): the integrations for networked services
        user_sub (str): the sub of the user whose entitlements we are getting

    Returns:
        LocalCachedEntitlements, None: if the users entitlement information was
            available, the entitlements, otherwise None
    """
    local_cache = await itgs.local_cache()

    raw = typing_cast(
        Optional[bytes], local_cache.get(f"entitlements:{user_sub}".encode("utf-8"))
    )
    if raw is None:
        return None

    return LocalCachedEntitlements.model_validate_json(raw)


async def set_entitlements_to_local(
    itgs: Itgs, *, user_sub: str, entitlements: LocalCachedEntitlements
) -> None:
    """Replaces the locally cached entitlement information for the user
    with the given sub with the given entitlements. The entitlements are
    cached for a short duration.

    Not generally used directly. Prefer `get_entitlement`

    Args:
        itgs (Itgs): the integrations for networked services
        user_sub (str): the sub of the user whose entitlements we are setting
        entitlements (LocalCachedEntitlements): the entitlements to set
    """
    local_cache = await itgs.local_cache()

    local_cache.set(
        f"entitlements:{user_sub}".encode("utf-8"),
        entitlements.__pydantic_serializer__.to_json(entitlements),
        expire=60 * 60 * 24,
        tag="collab",
    )


async def purge_entitlements_from_local(itgs: Itgs, *, user_sub: str) -> None:
    """Purges any entitlements stored about the given user from the local
    cache.

    This is typically called from the entitlements purging loop. Prefer
    `get_entitlement` with `force=True` to calling this directly.

    Args:
        itgs (Itgs): the integrations for networked services
        user_sub (str): the sub of the user whose entitlements we are purging
    """
    local_cache = await itgs.local_cache()

    local_cache.delete(f"entitlements:{user_sub}")


async def get_entitlement(
    itgs: Itgs, *, user_sub: str, identifier: str, force: bool = False
) -> Optional[CachedEntitlement]:
    """The main interface to the entitlements. This will fetch the entitlement
    information for the given user and identifier from the nearest available
    source, respecting the force flag and filling in any gaps in the cache.

    Despite the multilayer cache, this will very rapidly synchronize across
    instances due to an active purging mechanism.

    This will automatically detect and workaround any issue that prevents us
    from communicating with revenue cat - such as a revenue cat outage, a
    slowdown (excessively long response times), AWS networking issues, BGP
    issues, etc, in such a way that minimizes the impact.

    Args:
        itgs (Itgs): the integrations for networked services
        user_sub (str): the sub of the user whose entitlement we are getting
        identifier (str): the identifier of the entitlement we are getting
        force (bool): if True, the entitlement will be fetched from the source
            of truth regardless of whether it is available in a nearer cache. If
            false, the nearest cache will be used if available before falling
            back to the source of truth. Regardless of this flag, the caches
            will be filled in with fresher information if available and fetched
            - so in particular if force is True, the local cache and redis cache
            will both be updated every time. However, fetching an entitlement
            with force=True is not necessarily sufficient to purge caches for
            other entitlement identifiers.

    Returns:
        CachedEntitlement, None: if the user exists, the entitlement, otherwise None
    """

    if not force:
        local_cached = await get_entitlements_from_local(itgs, user_sub=user_sub)
        if local_cached is not None and identifier in local_cached.entitlements:
            return local_cached.entitlements[identifier]

        redis_cached_ent = await get_entitlement_from_redis(
            itgs, user_sub=user_sub, identifier=identifier
        )
        if redis_cached_ent is not None:
            local_cached = local_cached or LocalCachedEntitlements()
            local_cached.entitlements[identifier] = redis_cached_ent
            await set_entitlements_to_local(
                itgs, user_sub=user_sub, entitlements=local_cached
            )
            return redis_cached_ent

    if await is_revenue_cat_outage(itgs):
        return await fail_open_entitlement(
            itgs, user_sub=user_sub, identifier=identifier
        )

    now = time.time()
    try:
        to_cache = await asyncio.wait_for(
            get_entitlements_from_source(itgs, user_sub=user_sub, now=now), timeout=5
        )
    except Exception as exc:
        await handle_error(exc)
        await record_revenue_cat_error(itgs, now=now)
        return await fail_open_entitlement(
            itgs, user_sub=user_sub, identifier=identifier
        )

    if to_cache is None:
        return None

    if identifier not in to_cache.entitlements:
        to_cache.entitlements[identifier] = CachedEntitlement(
            is_active=False, expires_at=None, checked_at=now
        )

    await set_entitlements_to_local(itgs, user_sub=user_sub, entitlements=to_cache)
    await upsert_entitlements_to_redis(
        itgs, user_sub=user_sub, entitlements=to_cache.entitlements
    )
    await publish_purge_message(itgs, user_sub=user_sub, min_checked_at=now)
    return to_cache.entitlements[identifier]


COUNT_REVENUE_CAT_ERRORS_SCRIPT = """
local key = KEYS[1]
local later_than = tonumber(ARGV[1])

redis.call('zremrangebyscore', key, '-inf', later_than)
local count = redis.call('zcard', key)
return count
"""

COUNT_REVENUE_CAT_ERRORS_SCRIPT_HASH = hashlib.sha1(
    COUNT_REVENUE_CAT_ERRORS_SCRIPT.encode()
).hexdigest()
"""The sha1 for the lua script, used for evalsha"""


async def is_revenue_cat_outage(itgs: Itgs) -> bool:
    """Determines if there is a revenue cat outage, based on the number of
    recent errors in `revenue_cat_errors`, in redis. This will automatically
    clip the errors

    Not generally used directly. Prefer `get_entitlement`, which will handle
    revenue cat outages appropriately.

    Args:
        itgs (Itgs): the integrations for networked services

    Returns:
        bool: True if there is a revenue cat outage, False otherwise
    """
    redis = await itgs.redis()
    now = time.time()
    try:
        num_recent_errors = await redis.evalsha(  # type: ignore
            COUNT_REVENUE_CAT_ERRORS_SCRIPT_HASH, 1, "revenue_cat_errors", now - 60 * 5  # type: ignore
        )
    except NoScriptError:
        correct_sha = await redis.script_load(COUNT_REVENUE_CAT_ERRORS_SCRIPT)
        assert (
            correct_sha == COUNT_REVENUE_CAT_ERRORS_SCRIPT_HASH
        ), f"{correct_sha=} != {COUNT_REVENUE_CAT_ERRORS_SCRIPT_HASH=}"
        num_recent_errors = await redis.evalsha(  # type: ignore
            COUNT_REVENUE_CAT_ERRORS_SCRIPT_HASH, 1, "revenue_cat_errors", now - 60 * 5  # type: ignore
        )

    return num_recent_errors >= 10  # type: ignore


async def record_revenue_cat_error(itgs: Itgs, *, now: float) -> None:
    """Records an error in communicating with revenue cat in redis.

    Args:
        itgs (Itgs): the integrations for networked services
        now (float): the time the error occurred
    """
    redis = await itgs.redis()
    await redis.zadd("revenue_cat_errors", mapping={secrets.token_urlsafe(8): now})


async def fail_open_entitlement(
    itgs: Itgs, *, user_sub: str, identifier: str
) -> CachedEntitlement:
    """Creates and caches an active entitlement with the given identifier
    for the user with the given sub. This is intended to be used only if
    we can't communicate with the source of truth.

    Not generally used directly. Prefer `get_entitlement`, which will handle
    revenue cat outages appropriately.

    Args:
        itgs (Itgs): the integrations for networked services
        user_sub (str): the sub of the user whose entitlement we are getting
        identifier (str): the identifier of the entitlement we are getting

    Returns:
        CachedEntitlement: the fail open entitlement
    """
    now = time.time()
    fail_open_entitlement = CachedEntitlement(
        is_active=True, expires_at=now + 60 * 10, checked_at=now
    )
    await upsert_entitlements_to_redis(
        itgs, user_sub=user_sub, entitlements={identifier: fail_open_entitlement}
    )

    current_local = await get_entitlements_from_local(itgs, user_sub=user_sub)
    if current_local is None:
        current_local = LocalCachedEntitlements(entitlements={})
    current_local.entitlements[identifier] = fail_open_entitlement
    await set_entitlements_to_local(itgs, user_sub=user_sub, entitlements=current_local)
    await publish_purge_message(itgs, user_sub=user_sub, min_checked_at=now)
    return fail_open_entitlement


class EntitlementsPurgePubSubMessage(BaseModel):
    """The format of messages sent over the entitlements purge pubsub channel."""

    user_sub: str = Field()
    min_checked_at: float = Field(
        description="the cache should be purged of any entitlements checked before this unix time"
    )


async def publish_purge_message(
    itgs: Itgs, *, user_sub: str, min_checked_at: float
) -> None:
    """Notifies instances to purge any locally cached entitlements for the user with
    the given sub which were checked before the given time.
    """
    redis = await itgs.redis()
    await redis.publish(
        b"ps:entitlements:purge",
        EntitlementsPurgePubSubMessage(user_sub=user_sub, min_checked_at=min_checked_at)
        .model_dump_json()
        .encode("utf-8"),
    )


async def purge_cache_loop_async() -> Never:
    """The main function run to handle purging the cache when a notification
    is received on the appropriate redis channel
    """
    assert pps.instance is not None
    try:
        async with pps.PPSSubscription(
            pps.instance, "ps:entitlements:purge", "entitlements"
        ) as sub:
            while True:
                raw_data = await sub.read()
                data = EntitlementsPurgePubSubMessage.model_validate_json(raw_data)

                async with Itgs() as itgs:
                    local = await get_entitlements_from_local(
                        itgs, user_sub=data.user_sub
                    )
                    if local is None:
                        continue

                    old_len = len(local.entitlements)
                    local.entitlements = dict(
                        (k, v)
                        for k, v in local.entitlements.items()
                        if v.checked_at >= data.min_checked_at
                    )
                    if old_len > len(local.entitlements):
                        await set_entitlements_to_local(
                            itgs, user_sub=data.user_sub, entitlements=local
                        )
    except Exception as e:
        if pps.instance.exit_event.is_set() and isinstance(e, pps.PPSShutdownException):
            return  # type: ignore
        await handle_error(e)
    finally:
        print("entitlements purge loop exiting")
