"""The offerings module is a wrapper around 
https://www.revenuecat.com/docs/api-v1#tag/Project/operation/list-projects
which allows getting the offerings available to the user with the given sub
"""

import asyncio
import io
from typing import Awaitable, Dict, List, Literal, Optional, cast
from error_middleware import handle_error
from itgs import Itgs
from revenue_cat import (
    Offering,
    OfferingWithoutMetadata,
    Offerings,
    OfferingsWithoutMetadata,
)
import gzip
import random
from lifespan import lifespan_handler
import perpetual_pub_sub as pps
import os
import time
from users.lib.entitlements import is_revenue_cat_outage, record_revenue_cat_error

from users.lib.revenue_cat import get_or_create_latest_revenue_cat_id


async def get_offerings(
    itgs: Itgs,
    *,
    user_sub: str,
    platform: Literal["stripe", "playstore", "appstore"],
    force: bool,
    now: Optional[float] = None,
) -> Optional[OfferingsWithoutMetadata]:
    """Fetches the offerings available to the user with the given sub on
    the given platform.

    This will fetch or initialize the revenue cat id for the given user,
    then use that revenue cat id to get the offerings on that platform.
    The result has a 2-layer cache with coordinated updates, meaning that
    the result may be slightly stale, but it will be consistent "quickly".

    If `force` is true, we skip fetching from intermediate caches but will
    still update the caches before returning.

    This will use the ENVIRONMENT environment variable to remove any offers
    for the wrong environment, swapping the default according to the alternative
    indicated in its metadata.

    This will track errors with revenue cat, and in the event of an outage,
    return no offers without attempting to contact revenue cat.

    Args:
        itgs (Itgs): the integrations to (re)use
        user_sub (str): the sub of the user whose offerings you want to fetch
        platform ("stripe", "playstore", "appstore"): the platform for which to fetch the offerings
        force (bool): true to skip intermediate caches, increasing latency in
            exchange for improved consistency
        now (float, optional): the current time, in seconds since the epoch,
            or None for time.time()

    Returns:
        OfferingsWithoutMetadata, if any offers are available, otherwise None.
            Right now the metadata is stripped from the response completely as
            its been handled, but if we add new metadata unrelated to the environment,
            a new type that includes just that metadata could be a suitable response.
    """
    if now is None:
        now = time.time()

    revenue_cat_id = await get_or_create_latest_revenue_cat_id(
        itgs, user_sub=user_sub, now=now
    )
    if revenue_cat_id is None:
        return None

    if not force:
        raw = await read_offerings_from_local_cache(
            itgs, revenue_cat_id=revenue_cat_id, platform=platform
        )
        if raw is not None:
            return adapt_offerings_to_environment(_convert_from_stored(raw))
        raw = await read_offerings_from_remote_cache(
            itgs, revenue_cat_id=revenue_cat_id, platform=platform
        )
        if raw is not None:
            await write_offerings_to_local_cache(
                itgs, revenue_cat_id=revenue_cat_id, platform=platform, raw=raw
            )
            return adapt_offerings_to_environment(_convert_from_stored(raw))

    if await is_revenue_cat_outage(itgs):
        return None

    try:
        revenue_cat = await itgs.revenue_cat()
        to_cache = await revenue_cat.list_offerings(
            revenue_cat_id=revenue_cat_id, platform=platform
        )
    except Exception as exc:
        await handle_error(exc)
        await record_revenue_cat_error(itgs, now=now)
        return None

    if to_cache is None:
        return None

    raw = _convert_to_stored(to_cache)
    # writing to the local cache first is optional as it will be written to when
    # we send the publish message anyway, but reduces the impact of pub/sub
    # related issues
    await write_offerings_to_local_cache(
        itgs, revenue_cat_id=revenue_cat_id, platform=platform, raw=raw
    )
    await write_offerings_to_remote_cache(
        itgs, revenue_cat_id=revenue_cat_id, platform=platform, raw=raw
    )
    await push_offerings_to_all_local_caches(
        itgs, revenue_cat_id=revenue_cat_id, platform=platform, raw=raw
    )
    return adapt_offerings_to_environment(to_cache)


def adapt_offerings_to_environment(offerings: Offerings) -> OfferingsWithoutMetadata:
    """Returns the offerings with those for other environments removed
    and the metadata stripped as its been handled

    PERF:
        We could cache the adapted value rather than adapting every time,
        which would improve performance, but would mean it's more difficult
        to adjust this (or related) code in the event of either a bug or new
        metadata options since the original revenuecat data would be lost.
    """
    env = os.environ["ENVIRONMENT"]
    assert env in ("production", "dev"), env

    offerings_by_id: Dict[str, Offering] = dict()
    for offer in offerings.offerings:
        offerings_by_id[offer.identifier] = offer

    current_offer_og_env = offerings_by_id.get(offerings.current_offering_id)
    assert current_offer_og_env is not None, offerings
    if current_offer_og_env.metadata.environment == env:
        current_offer = current_offer_og_env
    else:
        alternative_id = current_offer_og_env.metadata.alternative.get(env)
        assert alternative_id is not None, (offerings, env)
        current_offer = offerings_by_id.get(alternative_id)
        assert current_offer is not None, (offerings, env)
        assert current_offer.metadata.environment == env, (offerings, env)

    relevant_offerings: List[OfferingWithoutMetadata] = []
    for offer in offerings.offerings:
        if offer.metadata.environment == env:
            relevant_offerings.append(offer.strip_metadata())

    return OfferingsWithoutMetadata(
        current_offering_id=current_offer.identifier, offerings=relevant_offerings
    )


async def read_offerings_from_local_cache(
    itgs: Itgs,
    *,
    revenue_cat_id: str,
    platform: Literal["stripe", "playstore", "appstore"],
) -> Optional[bytes]:
    """Fetches the offerings available to the user with the given sub on
    the given platform from the local cache, if available, in the stored
    format, otherwise returns None.
    """
    cache = await itgs.local_cache()
    return cast(
        Optional[bytes],
        cache.get(_cache_key(revenue_cat_id, platform)),
    )


async def write_offerings_to_local_cache(
    itgs: Itgs,
    *,
    revenue_cat_id: str,
    platform: Literal["stripe", "playstore", "appstore"],
    raw: bytes,
) -> None:
    """Writes the given serialized offerings to the local cache."""
    cache = await itgs.local_cache()
    cache.set(
        _cache_key(revenue_cat_id, platform),
        raw,
        expire=3600 + random.randint(2, 10),
        tag="collab",
    )


async def read_offerings_from_remote_cache(
    itgs: Itgs,
    *,
    revenue_cat_id: str,
    platform: Literal["stripe", "playstore", "appstore"],
) -> Optional[bytes]:
    """Fetches the offerings available to the user with the given sub on
    the given platform from the remote cache, if available, in the stored
    format, otherwise returns None.
    """
    redis = await itgs.redis()
    return await cast(
        Awaitable[Optional[bytes]], redis.get(_cache_key(revenue_cat_id, platform))
    )


async def write_offerings_to_remote_cache(
    itgs: Itgs,
    *,
    revenue_cat_id: str,
    platform: Literal["stripe", "playstore", "appstore"],
    raw: bytes,
) -> None:
    """Writes the given serialized offerings to the remote cache."""
    redis = await itgs.redis()
    await redis.set(
        _cache_key(revenue_cat_id, platform),
        raw,
        ex=3600,
    )


async def push_offerings_to_all_local_caches(
    itgs: Itgs,
    *,
    revenue_cat_id: str,
    platform: Literal["stripe", "playstore", "appstore"],
    raw: bytes,
) -> None:
    """Publishes a message which will cause the given serialized offerings to be
    pushed to all local caches
    """
    message = io.BytesIO()
    serd_revenue_cat_id = revenue_cat_id.encode("utf-8")
    message.write(len(serd_revenue_cat_id).to_bytes(2, "big"))
    message.write(serd_revenue_cat_id)
    serd_platform = platform.encode("utf-8")
    message.write(len(serd_platform).to_bytes(1, "big"))
    message.write(serd_platform)
    message.write(len(raw).to_bytes(8, "big"))
    message.write(raw)

    message_v = message.getvalue()

    redis = await itgs.redis()
    await redis.publish(b"ps:revenue_cat:offerings", message_v)


async def subscribe_to_offerings_pushes():
    assert pps.instance is not None

    try:
        async with pps.PPSSubscription(
            pps.instance, "ps:revenue_cat:offerings", "ulo_stop"
        ) as sub:
            async for message_raw in sub:
                message = io.BytesIO(message_raw)
                serd_revenue_cat_id_len = int.from_bytes(message.read(2), "big")
                revenue_cat_id = message.read(serd_revenue_cat_id_len).decode("utf-8")
                serd_platform_len = int.from_bytes(message.read(1), "big")
                serd_platform = message.read(serd_platform_len).decode("utf-8")
                raw_len = int.from_bytes(message.read(8), "big")
                raw = message.read(raw_len)

                assert serd_platform in (
                    "stripe",
                    "playstore",
                    "appstore",
                ), serd_platform
                platform = cast(
                    Literal["stripe", "playstore", "appstore"], serd_platform
                )

                async with Itgs() as itgs:
                    await write_offerings_to_local_cache(
                        itgs, revenue_cat_id=revenue_cat_id, platform=platform, raw=raw
                    )
    except Exception as e:
        if pps.instance.exit_event.is_set() and isinstance(e, pps.PPSShutdownException):
            return  # type: ignore
        await handle_error(e)
    finally:
        print("users.lib.offerings#subscribe_to_offerings_pushes exiting")


@lifespan_handler
async def do_subscribe_to_offerings_pushes():
    task = asyncio.create_task(subscribe_to_offerings_pushes())
    yield


def _cache_key(
    revenue_cat_id: str, platform: Literal["stripe", "playstore", "appstore"]
) -> bytes:
    return f"revenue_cat:offerings:{revenue_cat_id}:{platform}".encode("utf-8")


def _convert_to_stored(parsed: Offerings) -> bytes:
    """Converts the given offerings to a format suitable for storing in the
    cache.

    Args:
        offerings (Offerings): the offerings to convert

    Returns:
        bytes: the serialized offerings
    """
    return gzip.compress(parsed.__pydantic_serializer__.to_json(parsed), mtime=0)


def _convert_from_stored(raw: bytes) -> Offerings:
    """Converts the given serialized offerings to the original format.

    Args:
        raw (bytes): the serialized offerings

    Returns:
        Offerings: the deserialized offerings
    """
    return Offerings.model_validate_json(gzip.decompress(raw))
