import json
import secrets
import time
from typing import List, Literal, Optional, Tuple, cast

import pytz
from itgs import Itgs
from lib.basic_redis_lock import basic_redis_lock
from personalization.home.copy.lib.config import (
    HomescreenHeadline,
    generate_new_headline,
)
from personalization.home.copy.lib.context import (
    HomescreenCopyContext,
    HomescreenClientVariant,
)
from loguru import logger

from users.lib.streak import read_user_streak
from users.lib.timezones import (
    TimezoneTechniqueSlug,
    convert_timezone_technique_slug_to_db,
    get_user_timezone,
    need_set_timezone,
)
import unix_dates
import asyncio
from dataclasses import dataclass


@dataclass
class _DBInfo:
    taken_class: bool
    given_name: Optional[str]
    created_at: float


async def get_homescreen_copy(
    itgs: Itgs,
    *,
    user_sub: str,
    variant: HomescreenClientVariant,
    tz: str,
    tzt: TimezoneTechniqueSlug,
) -> Optional[HomescreenHeadline]:
    """Fetches the current home screen copy for the given user and client-requested
    variant.

    A different cache is used if the variant requested does not match the
    expected state (i.e, session start after taking a class, session end before
    taking a class), to avoid strange messages (e.g., "Only two more to go!"
    when theres really 1 more to go not counting today, which is already done)

    Args:
        itgs (Itgs): the integrations to (re)use
        user_sub (str): the sub of the user whose home screen copy should be fetched
        variant (HomescreenClientVariant): the variant requested by the client

    Returns:
        (HomescreenHeadline, None): the headline to display on the home screen, or None
            if the user no longer exists
    """
    req_id = secrets.token_urlsafe(4)
    request_at = time.time()
    logger.debug(
        f"get_homescreen_copy for {user_sub=}, {variant=} assigned {req_id=}, {request_at=}"
    )

    tz_is_valid = False
    try:
        user_tz = pytz.timezone(tz)
        tz_is_valid = True
    except pytz.UnknownTimeZoneError:
        logger.debug(
            f"{req_id=} ignoring invalid provided timezone {tz=} for {user_sub=}, using stored"
        )
        user_tz = await get_user_timezone(itgs, user_sub=user_sub)

    unix_date_today = unix_dates.unix_timestamp_to_unix_date(request_at, tz=user_tz)
    cache_key_taken_class = (
        f"users:{user_sub}:homescreen_copy:{variant}:{unix_date_today}:True".encode(
            "utf-8"
        )
    )
    cache_key_not_taken_class = (
        f"users:{user_sub}:homescreen_copy:{variant}:{unix_date_today}:False".encode(
            "utf-8"
        )
    )

    async def _get_cached() -> Tuple[Optional[bytes], Optional[bytes]]:
        redis = await itgs.redis()
        async with redis.pipeline(transaction=False) as pipe:
            await pipe.get(cache_key_taken_class)
            await pipe.get(cache_key_not_taken_class)
            return tuple(await pipe.execute())

    async def _get_db_info() -> Optional[_DBInfo]:
        conn = await itgs.conn()
        cursor = conn.cursor()

        for consistency in cast(List[Literal["none", "strong"]], ["none", "strong"]):
            response = await cursor.executeunified3(
                (
                    (
                        "SELECT given_name, created_at FROM users WHERE sub=?",
                        (user_sub,),
                    ),
                    (
                        "SELECT 1 FROM users, user_journeys "
                        "WHERE"
                        " users.sub = ?"
                        " AND user_journeys.user_id = users.id"
                        " AND user_journeys.created_at_unix_date = ?",
                        (user_sub, unix_date_today),
                    ),
                ),
                read_consistency=consistency,
                freshness="1m",
            )
            if response[0].results:
                return _DBInfo(
                    taken_class=bool(response[1].results),
                    given_name=cast(Optional[str], response[0].results[0][0]),
                    created_at=cast(float, response[0].results[0][1]),
                )

        return None

    cached_task = asyncio.create_task(_get_cached())
    db_info_task = asyncio.create_task(_get_db_info())

    cached_taken, cached_not_taken = await cached_task
    if cached_taken is not None:
        logger.info(f"{req_id=} CACHE HIT (taken class short-circuit)")
        db_info_task.cancel()
        return HomescreenHeadline.model_validate_json(cached_taken)

    if cached_not_taken is not None:
        db_info_early = await db_info_task
        if db_info_early is not None and not db_info_early.taken_class:
            logger.info(f"{req_id=} CACHE HIT (not taken class)")
            return HomescreenHeadline.model_validate_json(cached_not_taken)

    logger.debug(f"{req_id=} cache miss")

    streak = await read_user_streak(itgs, sub=user_sub, prefer="model")
    db_info = await db_info_task
    if db_info is None:
        logger.error(f"{req_id=} user not found, returning None")
        return None

    cache_key = (
        cache_key_taken_class if db_info.taken_class else cache_key_not_taken_class
    )
    redis = await itgs.redis()
    async with basic_redis_lock(
        itgs,
        f"users:{user_sub}:homescreen_copy:{variant}:{unix_date_today}:{db_info.taken_class}:lock".encode(
            "utf-8"
        ),
        spin=True,
        timeout=3,
    ):
        result = await redis.get(cache_key)
        if result is not None:
            logger.info(f"{req_id=} CACHE HIT (post-lock)")
            return HomescreenHeadline.model_validate_json(result)
        logger.debug(f"{req_id=} cache miss (post-lock)")

        ctx = HomescreenCopyContext(
            user_sub=user_sub,
            given_name=db_info.given_name,
            client_variant=variant,
            taken_class_today=db_info.taken_class,
            user_created_at=db_info.created_at,
            show_at=request_at,
            show_tz=user_tz,
            streak=streak,
        )
        logger.debug(f"{req_id=} generating using {ctx=}")
        model = await generate_new_headline(itgs, ctx)
        raw = model.__pydantic_serializer__.to_json(model)
        logger.debug(f"{req_id=} generated {raw=}")
        await redis.set(cache_key, raw, ex=3600)
        logger.debug(f"{req_id=} cached, releasing lock before storing in db")

    queries: List[Tuple[str, list]] = []

    if tz_is_valid:
        logger.debug(f"{req_id=} hit on valid timezone, checking if need to store")
        if await need_set_timezone(itgs, user_sub=user_sub, timezone=tz):
            logger.debug(
                f"{req_id=} sending user timezone update along with log record"
            )
            timezone_technique = convert_timezone_technique_slug_to_db(tzt)

            queries.append(
                (
                    "INSERT INTO user_timezone_log ("
                    " uid, user_id, timezone, source, style, guessed, created_at"
                    ") "
                    "SELECT"
                    " ?, users.id, ?, ?, ?, ?, ? "
                    "FROM users "
                    "WHERE"
                    " users.sub = ?"
                    " AND (users.timezone IS NULL OR users.timezone <> ?)",
                    [
                        f"oseh_utzl_{secrets.token_urlsafe(16)}",
                        tz,
                        "read_home_copy",
                        timezone_technique.style,
                        timezone_technique.guessed,
                        ctx.show_at,
                        user_sub,
                        tz,
                    ],
                )
            )
            queries.append(
                ("UPDATE users SET timezone = ? WHERE sub = ?", [tz, user_sub])
            )
        else:
            logger.debug(f"{req_id=} no need to store timezone")

    queries.append(
        (
            "INSERT INTO user_home_screen_copy ("
            " uid, user_id, variant, slug, composed_slugs, created_at"
            ") "
            "SELECT"
            " ?, users.id, ?, ?, ?, ? "
            "FROM users"
            " WHERE users.sub=?",
            [
                f"oseh_uhsc_{secrets.token_urlsafe(16)}",
                variant,
                model.slug,
                json.dumps(model.composed_slugs, separators=(",", ":")),
                ctx.show_at,
                user_sub,
            ],
        )
    )

    conn = await itgs.conn()
    cursor = conn.cursor()
    await cursor.executemany3(queries)
    logger.info(f"{req_id=} MISS -> {model}")
    return model
