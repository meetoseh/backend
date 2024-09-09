import asyncio
from dataclasses import dataclass
from datetime import date
import io
import random
import secrets
import time
from typing import List, Optional, cast
from pydantic import BaseModel, Field, TypeAdapter
from error_middleware import handle_error, handle_warning
from itgs import Itgs
import gzip
import unix_dates
from personalization.home.images.lib.home_screen_image_flag import (
    HomeScreenImageFlag,
    get_home_screen_image_flag_by_datetime_day_of_week,
    get_home_screen_image_flag_by_month,
)
import pytz
from lifespan import lifespan_handler
import perpetual_pub_sub as pps
import users.lib.entitlements as entitlements


@dataclass
class UserHomeScreenImage:
    image_uid: str
    """The UID of the image file that they should see"""

    thumbhash: str
    """The base64url encoded thumbhash of the image at a typical resolution"""


class AvailableHomeScreenImage(BaseModel):
    home_screen_image_uid: str = Field()
    """The uid of the row in home_screen_images"""

    start_time: float = Field()
    """The earliest time, in seconds from the start of the indicated day
    that this can be shown.
    """

    end_time: float = Field()
    """The latest time, in seconds from the start of the indicated day
    that this can be shown. 
    """


_available_home_screen_images_adapter: TypeAdapter[List[AvailableHomeScreenImage]] = (
    TypeAdapter(List[AvailableHomeScreenImage])
)


async def read_home_screen_image(
    itgs: Itgs, *, user_sub: str, now: float, timezone: str
) -> UserHomeScreenImage:
    """Determines which home screen image the user with the given sub should
    see.
    """
    stickiness_result = await _read_home_screen_image_using_stickiness(
        itgs, user_sub=user_sub, now=now
    )
    if stickiness_result is not None:
        return stickiness_result

    recent_images_task = asyncio.create_task(
        _read_recent_user_home_screen_images(itgs, user_sub=user_sub, now=now)
    )
    try:
        tz = pytz.timezone(timezone)
    except:
        tz = pytz.timezone("America/Los_Angeles")

    unix_date = unix_dates.unix_timestamp_to_unix_date(now, tz=tz)
    start_of_day = unix_dates.unix_date_to_timestamp(unix_date, tz=tz)
    seconds_since_midnight = now - start_of_day

    pro_entitlement = await entitlements.get_entitlement(
        itgs, user_sub=user_sub, identifier="pro"
    )
    is_pro = pro_entitlement is not None and pro_entitlement.is_active

    date_iso8601 = unix_dates.unix_date_to_date(unix_date).isoformat()
    prev_date_iso8601 = unix_dates.unix_date_to_date(unix_date - 1).isoformat()

    prev_wrapped_available, available, recent_images = await asyncio.gather(
        _read_available_home_screen_images(
            itgs,
            date_iso8601=prev_date_iso8601,
            has_pro=is_pro,
            wrapped_only=True,
            now=now,
        ),
        _read_available_home_screen_images(
            itgs, date_iso8601=date_iso8601, has_pro=is_pro, wrapped_only=False, now=now
        ),
        recent_images_task,
    )

    seconds_since_prev_midnight = seconds_since_midnight + 86400
    relevant_prev = [
        r
        for r in prev_wrapped_available
        if r.start_time <= seconds_since_prev_midnight
        and r.end_time > seconds_since_prev_midnight
    ]
    relevant = [
        r
        for r in available
        if r.start_time <= seconds_since_midnight
        and r.end_time > seconds_since_midnight
    ]

    hsi_uids_by_times_seen = dict()
    for img in relevant_prev:
        hsi_uids_by_times_seen[img.home_screen_image_uid] = 0
    for img in relevant:
        hsi_uids_by_times_seen[img.home_screen_image_uid] = 0

    for uid in recent_images:
        if uid in hsi_uids_by_times_seen:
            hsi_uids_by_times_seen[uid] += 1

    min_times_seen = min(hsi_uids_by_times_seen.values(), default=0)
    candidates = [
        uid
        for uid, times_seen in hsi_uids_by_times_seen.items()
        if times_seen == min_times_seen
    ]
    if not candidates:
        await handle_warning(
            f"{__name__}:no_candidates",
            f"{user_sub=} has no candidate images at {now=}, {timezone=} - serving an arbitrary home screen image",
        )
        conn = await itgs.conn()
        cursor = conn.cursor("none")
        response = await cursor.execute("SELECT uid FROM home_screen_images LIMIT 1")
        if not response.results:
            raise ValueError("No home screen images available")
        choice = cast(str, response.results[0][0])
    else:
        choice = random.choice(candidates)

    return await _try_select_home_screen_image(
        itgs, user_sub=user_sub, now=now, hsi_uid=choice
    )


async def purge_home_screen_images_cache(itgs: Itgs) -> None:
    """Should be called if the admin interface is used to modify which home
    screen images are available. Destroys the cache so that all instances will
    serve data at least as fresh as a weak consistency level db query at the
    current instant.
    """
    await _delete_available_home_screen_images_from_remote_cache(
        itgs, iso8601_dates=_determine_purge_dates(time.time())
    )
    await _push_purge_to_all_local_caches(itgs)


async def _try_select_home_screen_image(
    itgs: Itgs, *, user_sub: str, now: float, hsi_uid: str
) -> UserHomeScreenImage:
    conn = await itgs.conn()
    cursor = conn.cursor("strong")

    new_uid = f"oseh_uhsi_{secrets.token_urlsafe(16)}"
    response = await cursor.executeunified3(
        (
            (_STICKINESS_QUERY, (user_sub, now - 3600)),
            (
                # --SEARCH users USING COVERING INDEX sqlite_autoindex_users_1 (sub=?)
                # --SCALAR SUBQUERY 2
                #   |--SEARCH ushi USING COVERING INDEX user_home_screen_images_user_id_created_at_idx (user_id=? AND created_at>?)
                #   |--SCALAR SUBQUERY 1
                #      |--SEARCH u USING COVERING INDEX sqlite_autoindex_users_1 (sub=?)
                # --SEARCH home_screen_images USING COVERING INDEX sqlite_autoindex_home_screen_images_1 (uid=?)
                """
INSERT INTO user_home_screen_images (
    uid, user_id, home_screen_image_id, created_at
)
SELECT
    ?, users.id, home_screen_images.id, ?
FROM users, home_screen_images
WHERE
    users.sub = ?
    AND home_screen_images.uid = ?
    AND NOT EXISTS (
        SELECT 1 FROM user_home_screen_images AS ushi
        WHERE
            ushi.user_id = (SELECT u.id FROM users AS u WHERE u.sub = ?)
            AND ushi.created_at > ?
    )
                """,
                (new_uid, now, user_sub, hsi_uid, user_sub, now - 3600),
            ),
            (
                # this is imperfect because created_at could be exactly equal,
                # but can be processed where the "correlated subquery" will only
                # ever occur against exactly 1 row, which is important since it
                # requires a search
                # --SEARCH user_home_screen_images USING INTEGER PRIMARY KEY (rowid=?)
                # --SCALAR SUBQUERY 2
                #   |--SEARCH uhsi USING COVERING INDEX user_home_screen_images_user_id_created_at_idx (user_id=?)
                #   |--SCALAR SUBQUERY 1
                #      |--SEARCH users USING COVERING INDEX sqlite_autoindex_users_1 (sub=?)
                # --CORRELATED SCALAR SUBQUERY 3
                #   |--SEARCH uhsi USING COVERING INDEX user_home_screen_images_user_id_created_at_idx (user_id=? AND created_at>?)
                """
DELETE FROM user_home_screen_images
WHERE
    user_home_screen_images.id = (
        SELECT uhsi.id FROM user_home_screen_images AS uhsi
        WHERE
            uhsi.user_id = (SELECT users.id FROM users WHERE users.sub = ?)
        ORDER BY uhsi.created_at ASC, uhsi.id ASC
        LIMIT 1
    )
    AND (
        SELECT COUNT(*) FROM user_home_screen_images AS uhsi
        WHERE
            uhsi.user_id = user_home_screen_images.user_id
            AND uhsi.created_at > user_home_screen_images.created_at
    ) > 111
                """,
                (user_sub,),
            ),
            (
                # --SEARCH home_screen_images USING INDEX sqlite_autoindex_home_screen_images_1 (uid=?)
                # --SEARCH image_files USING INTEGER PRIMARY KEY (rowid=?)
                # --SEARCH image_file_exports USING INDEX image_file_exports_image_file_id_format_width_height_idx (image_file_id=? AND format=? AND width=? AND height=?)
                # --USE TEMP B-TREE FOR ORDER BY
                """
SELECT
    image_files.uid,
    image_file_exports.thumbhash
FROM home_screen_images, image_files, image_file_exports
WHERE
    home_screen_images.uid = ?
    AND home_screen_images.darkened_image_file_id = image_files.id
    AND image_file_exports.image_file_id = image_files.id
    AND image_file_exports.width = 390
    AND image_file_exports.height = 304
    AND image_file_exports.format = 'webp'
ORDER BY image_file_exports.uid ASC
LIMIT 1
                """,
                (hsi_uid,),
            ),
        ),
    )

    if response[0].results:
        return UserHomeScreenImage(
            image_uid=cast(str, response[0].results[0][0]),
            thumbhash=cast(str, response[0].results[0][1]),
        )

    if response[1].rows_affected is not None and response[1].rows_affected > 0:
        assert response[3].results, response
        return UserHomeScreenImage(
            image_uid=cast(str, response[3].results[0][0]),
            thumbhash=cast(str, response[3].results[0][1]),
        )

    assert not response[3].results, response
    raise ValueError(f"There is no home screen image with {hsi_uid=}")


async def _read_home_screen_image_using_stickiness(
    itgs: Itgs, *, user_sub: str, now: float
) -> Optional[UserHomeScreenImage]:
    """Uses the stickiness feature (a user should see the same home screen
    image for at least 1 hour before it changes) to determine which home screen
    the user should see, if it applies.

    This uses none-level consistency and thus, on its own, is not an effective
    ratelimiting mechanism.
    """
    conn = await itgs.conn()
    cursor = conn.cursor("none")
    response = await cursor.execute(
        _STICKINESS_QUERY,
        (user_sub, now - 3600),
    )
    if not response.results:
        return None

    return UserHomeScreenImage(
        image_uid=cast(str, response.results[0][0]),
        thumbhash=cast(str, response.results[0][1]),
    )


async def _read_recent_user_home_screen_images(
    itgs: Itgs, *, user_sub: str, now: float
) -> List[str]:
    """Reads the uids of the home_screen_image rows that the user
    has seen recently, in no particular order and potentially including
    duplicates.

    This uses none-level consistency and thus may return slightly stale
    data.

    This relies on all callers respecting the user-level maximum insert
    rate to prevent an excessive number of rows from being returned.
    """
    conn = await itgs.conn()
    cursor = conn.cursor("none")
    response = await cursor.execute(
        """
SELECT
    home_screen_images.uid
FROM users, user_home_screen_images, home_screen_images
WHERE
    users.sub = ?
    AND user_home_screen_images.user_id = users.id
    AND user_home_screen_images.created_at > ?
    AND user_home_screen_images.home_screen_image_id = home_screen_images.id
        """,
        (user_sub, now - 60 * 60 * 24 * 30),
    )

    return [r[0] for r in response.results or []]


async def _read_available_home_screen_images(
    itgs: Itgs, *, date_iso8601: str, has_pro: bool, wrapped_only: bool, now: float
) -> List[AvailableHomeScreenImage]:
    """Determines what home screen images are available for the given date
    for someone which does/does not have the `pro` revenuecat entitlement.

    This value is retrieved from a 2-layer cache with eager invalidation,
    so it may be stale, but it will not typically be excessively so.

    In order to keep cache hit rate relatively high, this does not consider
    the time of day restriction on home screen images. Instead, that information
    is returned so that the caller can filter the list as appropriate.

    NOTE:
        If you are interested in day X, you will need to request the available
        images on day X with `wrapped_only=False` and day X-1 with `wrapped_only=True`

    Args:
        itgs (Itgs): the integrations to (re)use
        date_iso8601 (str): the date to check, in ISO 8601 format, i.e.,
            YYYY-MM-DD
        has_pro (bool): whether the user has the pro entitlement or not
        wrapped_only (bool): If true, the result will only include rows where
            the original `end_time` is greater than 86400, i.e., the image
            wraps onto the following day. It is never necessary to set this to
            True, but it is an important optimization as this greatly reduces
            the number of rows returned.
        now (float): the current time in seconds since the epoch, for live_at

    Returns:
        List[AvailableHomeScreenImage]: the available home screen images
    """
    raw = await _read_available_home_screen_images_from_local_cache(
        itgs, date_iso8601=date_iso8601, has_pro=has_pro, wrapped_only=wrapped_only
    )
    if raw is not None:
        return _convert_available_from_stored(raw)

    if wrapped_only:
        unwrapped_raw = await _read_available_home_screen_images_from_local_cache(
            itgs, date_iso8601=date_iso8601, has_pro=has_pro, wrapped_only=False
        )
        if unwrapped_raw is not None:
            unwrapped = _convert_available_from_stored(unwrapped_raw)
            wrapped = [r for r in unwrapped if r.end_time > 86400]
            raw = _convert_available_to_stored(wrapped)
            await _write_available_home_screen_images_to_local_cache(
                itgs,
                date_iso8601=date_iso8601,
                has_pro=has_pro,
                wrapped_only=wrapped_only,
                available=raw,
            )
            return wrapped

    raw = await _read_available_home_screen_images_from_remote_cache(
        itgs, date_iso8601=date_iso8601, has_pro=has_pro, wrapped_only=wrapped_only
    )
    if raw is not None:
        await _write_available_home_screen_images_to_local_cache(
            itgs,
            date_iso8601=date_iso8601,
            has_pro=has_pro,
            wrapped_only=wrapped_only,
            available=raw,
        )
        return _convert_available_from_stored(raw)

    if wrapped_only:
        unwrapped_raw = await _read_available_home_screen_images_from_remote_cache(
            itgs, date_iso8601=date_iso8601, has_pro=has_pro, wrapped_only=False
        )
        if unwrapped_raw is not None:
            unwrapped = _convert_available_from_stored(unwrapped_raw)
            wrapped = [r for r in unwrapped if r.end_time > 86400]
            raw = _convert_available_to_stored(wrapped)
            await _write_available_home_screen_images_to_local_cache(
                itgs,
                date_iso8601=date_iso8601,
                has_pro=has_pro,
                wrapped_only=wrapped_only,
                available=raw,
            )
            await _write_available_home_screen_images_to_remote_cache(
                itgs,
                date_iso8601=date_iso8601,
                has_pro=has_pro,
                wrapped_only=wrapped_only,
                available=raw,
            )
            return wrapped

    unix_date = unix_dates.date_to_unix_date(date.fromisoformat(date_iso8601))

    day_flags = _determine_day_flags(unix_date)
    pro_flag = (
        HomeScreenImageFlag.VISIBLE_WITH_PRO
        if has_pro
        else HomeScreenImageFlag.VISIBLE_WITHOUT_PRO
    )
    flags = day_flags | pro_flag

    available = await _read_unadj_available_home_screen_images_from_db(
        itgs,
        date_iso8601=date_iso8601,
        flags=flags,
        live_leq=now,
        wrapped_only=wrapped_only,
    )
    raw = _convert_available_to_stored(available)
    await _write_available_home_screen_images_to_local_cache(
        itgs,
        date_iso8601=date_iso8601,
        has_pro=has_pro,
        wrapped_only=wrapped_only,
        available=raw,
    )
    await _write_available_home_screen_images_to_remote_cache(
        itgs,
        date_iso8601=date_iso8601,
        has_pro=has_pro,
        wrapped_only=wrapped_only,
        available=raw,
    )
    await _push_available_home_screen_images_to_all_local_caches(
        itgs,
        date_iso8601=date_iso8601,
        has_pro=has_pro,
        wrapped_only=wrapped_only,
        available=raw,
    )
    return available


async def _read_available_home_screen_images_from_local_cache(
    itgs: Itgs, *, date_iso8601: str, has_pro: bool, wrapped_only: bool
) -> Optional[bytes]:
    cache = await itgs.local_cache()
    return cast(
        Optional[bytes],
        cache.get(_available_cache_key(date_iso8601, has_pro, wrapped_only)),
    )


async def _write_available_home_screen_images_to_local_cache(
    itgs: Itgs,
    *,
    date_iso8601: str,
    has_pro: bool,
    wrapped_only: bool,
    available: bytes,
) -> None:
    cache = await itgs.local_cache()
    cache.set(
        _available_cache_key(date_iso8601, has_pro, wrapped_only),
        available,
        tag="collab",
        expire=86400 * 2,
    )


async def _delete_available_home_screen_images_from_local_cache(
    itgs: Itgs, *, iso8601_dates: List[str]
) -> None:
    cache = await itgs.local_cache()
    for date in iso8601_dates:
        for has_pro in (True, False):
            for wrapped_only in (True, False):
                cache.delete(_available_cache_key(date, has_pro, wrapped_only))


async def _read_available_home_screen_images_from_remote_cache(
    itgs: Itgs, *, date_iso8601: str, has_pro: bool, wrapped_only: bool
) -> Optional[bytes]:
    redis = await itgs.redis()
    return await redis.get(_available_cache_key(date_iso8601, has_pro, wrapped_only))


async def _write_available_home_screen_images_to_remote_cache(
    itgs: Itgs,
    *,
    date_iso8601: str,
    has_pro: bool,
    wrapped_only: bool,
    available: bytes,
) -> None:
    redis = await itgs.redis()
    await redis.set(
        _available_cache_key(date_iso8601, has_pro, wrapped_only),
        available,
        ex=86400 * 2 + 60,
    )


async def _delete_available_home_screen_images_from_remote_cache(
    itgs: Itgs, *, iso8601_dates: List[str]
) -> None:
    keys: List[bytes] = []
    for date in iso8601_dates:
        for has_pro in (True, False):
            for wrapped_only in (True, False):
                keys.append(_available_cache_key(date, has_pro, wrapped_only))

    redis = await itgs.redis()
    await redis.delete(*keys)


async def _read_unadj_available_home_screen_images_from_db(
    itgs: Itgs,
    *,
    date_iso8601: str,
    flags: HomeScreenImageFlag,
    live_leq: float,
    wrapped_only: bool,
) -> List[AvailableHomeScreenImage]:
    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    response = await cursor.execute(
        f"""
SELECT
    uid,
    start_time,
    end_time
FROM home_screen_images
WHERE
    (flags & ?) = ?
    {'AND end_time > 86400' if wrapped_only else ''}
    AND live_at <= ?
    AND (
        dates is NULL
        OR (
            EXISTS (
                SELECT 1 FROM json_each(dates) WHERE value = ?
            )
        )
    )
        """,
        [flags, flags, live_leq, date_iso8601],
    )

    return [
        AvailableHomeScreenImage(
            home_screen_image_uid=cast(str, r[0]),
            start_time=cast(float, r[1]),
            end_time=cast(float, r[2]),
        )
        for r in response.results or []
    ]


async def _push_available_home_screen_images_to_all_local_caches(
    itgs: Itgs,
    *,
    date_iso8601: str,
    has_pro: bool,
    wrapped_only: bool,
    available: bytes,
) -> None:
    msg = io.BytesIO()
    msg.write((1).to_bytes(1, "big", signed=False))
    msg.write(date_iso8601.encode("ascii"))
    msg.write(int(has_pro).to_bytes(1, "big", signed=False))
    msg.write(int(wrapped_only).to_bytes(1, "big", signed=False))
    msg.write(len(available).to_bytes(8, "big", signed=False))
    msg.write(available)

    redis = await itgs.redis()
    await redis.publish(_available_ps_key, msg.getvalue())


async def _push_purge_to_all_local_caches(itgs: Itgs) -> None:
    msg = io.BytesIO()
    msg.write((0).to_bytes(1, "big", signed=False))

    redis = await itgs.redis()
    await redis.publish(_available_ps_key, msg.getvalue())


async def _handle_local_purge(itgs: Itgs, *, now: float) -> None:
    iso8601_dates = _determine_purge_dates(now)
    await _delete_available_home_screen_images_from_local_cache(
        itgs, iso8601_dates=iso8601_dates
    )


async def _handle_cache_pushes_forever() -> None:
    assert pps.instance is not None

    try:
        async with pps.PPSSubscription(
            pps.instance, _available_ps_key.decode("utf-8"), "hsi_hcpf"
        ) as sub:
            async for raw_message_bytes in sub:
                msg = io.BytesIO(raw_message_bytes)
                is_data_push = int.from_bytes(msg.read(1), "big", signed=False) == 1
                if not is_data_push:
                    async with Itgs() as itgs:
                        await _handle_local_purge(itgs, now=time.time())
                    continue

                date_iso8601 = msg.read(10).decode("ascii")
                has_pro = bool(int.from_bytes(msg.read(1), "big", signed=False))
                wrapped_only = bool(int.from_bytes(msg.read(1), "big", signed=False))
                available_len = int.from_bytes(msg.read(8), "big", signed=False)
                available = msg.read(available_len)

                async with Itgs() as itgs:
                    await _write_available_home_screen_images_to_local_cache(
                        itgs,
                        date_iso8601=date_iso8601,
                        has_pro=has_pro,
                        wrapped_only=wrapped_only,
                        available=available,
                    )
    except Exception as e:
        if pps.instance.exit_event.is_set() and isinstance(e, pps.PPSShutdownException):
            return  # type: ignore
        await handle_error(e)
    finally:
        print("users.lib.home_screen_images#_handle_cache_pushes_forever exiting")


@lifespan_handler
async def _handle_cache_pushes():
    task = asyncio.create_task(_handle_cache_pushes_forever())
    yield


def _determine_day_flags(unix_date: int) -> HomeScreenImageFlag:
    dt = unix_dates.unix_date_to_date(unix_date)
    return get_home_screen_image_flag_by_month(
        dt.month
    ) | get_home_screen_image_flag_by_datetime_day_of_week(dt.weekday())


def _determine_purge_dates(now: float) -> List[str]:
    """Determines which dates, in iso8601 format, need to be purged to ensure
    all requests at the given time will not be retrieved from the cache, regardless
    of the timezone.
    """
    res: List[str] = []

    start_unix_date = unix_dates.unix_timestamp_to_unix_date(
        now - 86400 * 3, tz=pytz.utc
    )
    for i in range(7):
        dt = unix_dates.unix_date_to_date(start_unix_date + i)
        res.append(dt.isoformat())

    return res


def _convert_available_to_stored(available: List[AvailableHomeScreenImage]) -> bytes:
    return gzip.compress(
        _available_home_screen_images_adapter.dump_json(available), mtime=0
    )


def _convert_available_from_stored(raw: bytes) -> List[AvailableHomeScreenImage]:
    return _available_home_screen_images_adapter.validate_json(gzip.decompress(raw))


def _available_cache_key(date_iso8601: str, has_pro: bool, wrapped_only: bool) -> bytes:
    return f"home_screen_images:{date_iso8601}:{has_pro}:{wrapped_only}".encode("utf-8")


_available_ps_key = b"ps:home_screen_images:available"

# --SEARCH users USING COVERING INDEX sqlite_autoindex_users_1 (sub=?)
# --SEARCH user_home_screen_images USING INDEX user_home_screen_images_user_id_created_at_idx (user_id=? AND created_at>?)
# --SEARCH home_screen_images USING INTEGER PRIMARY KEY (rowid=?)
# --SEARCH image_files USING INTEGER PRIMARY KEY (rowid=?)
# --SEARCH image_file_exports USING INDEX image_file_exports_image_file_id_format_width_height_idx (image_file_id=? AND format=? AND width=? AND height=?)
# --USE TEMP B-TREE FOR RIGHT PART OF ORDER BY
_STICKINESS_QUERY = """
SELECT
    image_files.uid,
    image_file_exports.thumbhash
FROM users, user_home_screen_images, home_screen_images, image_files, image_file_exports
WHERE
    users.sub = ?
    AND user_home_screen_images.user_id = users.id
    AND user_home_screen_images.created_at > ?
    AND user_home_screen_images.home_screen_image_id = home_screen_images.id
    AND home_screen_images.darkened_image_file_id = image_files.id
    AND image_file_exports.image_file_id = image_files.id
    AND image_file_exports.width = 390
    AND image_file_exports.height = 304
    AND image_file_exports.format = 'webp'
ORDER BY user_home_screen_images.created_at DESC, image_file_exports.uid ASC
LIMIT 1
"""
