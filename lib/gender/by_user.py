"""Allows fetching, guessing, or setting the gender for a particular user. This uses
a 3-layer cache on our end for guesses (database, redis, instance disk), which
means we usually do not need to repeat a guess for the same user (which could
lead to inconsistent results).

This uses a lock with active coordination and steal-on-timeout semantics to
avoid duplicate requests to gender-api.com under load with minimal impact on
availability when an instance dies mid-request.
"""

import asyncio
import io
import itertools
import os
import random
import secrets
import time
import perpetual_pub_sub as pps
from typing import Dict, List, Literal, Optional, Tuple, Union, cast
from dataclasses import dataclass
from pydantic import BaseModel, Field
from error_middleware import handle_error, handle_warning
from lifespan import lifespan_handler
from itgs import Itgs
from lib.gender.gender_source import (
    GenderByEmailAddressSource,
    GenderByFallbackSource,
    GenderByFirstNameSource,
    GenderSource,
    gender_source_adapter,
)
from redis_helpers.zadd_exact_window import zadd_exact_window_safe
from redis_helpers.zcard_exact_window import zcard_exact_window_safe
from loguru import logger


Gender = Literal["male", "female", "nonbinary", "unknown"]


class GenderByUserUserNotFoundError(Exception):
    """Raised when the user with the given sub doesn't appear to exist"""

    def __init__(self, sub: str) -> None:
        super().__init__(f"User {sub} not found")


class GenderByUserNotSetError(Exception):
    """Raised if only_if_set is True but the user has no gender set"""

    def __init__(self, sub: str) -> None:
        super().__init__(f"User {sub} has no gender set and guessing was disallowed")


class GenderWithSource(BaseModel):
    gender: Gender = Field()
    source: GenderSource = Field()


gender_subscriptions_by_sub: Dict[str, List[asyncio.Event]] = dict()
"""Instances communicate via redis pub/sub whenever genders are guessed
or caches are purged. Upon receiving a message indicating another instance
_set_ the gender associated with the user with the given sub, _after_
filling our local cache, we will set any events in the list for that sub
in this dict and remove the list from the dict.

This is not thread-safe or process-safe. It must only be interacted with
on the main asyncio thread.
"""


async def get_gender_by_user(
    itgs: Itgs, /, *, sub: str, locale: Optional[str], only_if_set: bool = False
) -> GenderWithSource:
    """Determines the gender of the user with the given sub, fetching from
    caches where possible and filling missed caches. This can be called
    concurrently across either processes or instances and will not
    typically result in duplicate API requests. This is not thread-safe; it
    must be called on the primary asyncio thread for the current process.

    The result may be slightly stale due to coordination delays, e.g., if the
    users gender just changed and the cache was purged via `purge_gender_by_user_cache`,
    this instance may not have received the message to purge its cache yet.

    Args:
        itgs (Itgs): the integrations to (re)use
        sub (str): the sub of the user whose gender to fetch
        locale (Optional[str]): the locale of the user, as an IETF BCP 47 language tag,
            e.g., en-US. May use underscores instead of dashes as a separator. Improves
            the accuracy of guesses, but is not required.
        only_if_set (bool): If True this will not result in modifications to the database;
            instead it will return `None` if there is no active gender for the user (either
            from guesses or from manual setting). Defaults to False. If False, if the user
            exists and has some kind of identifier (e.g., a name or email), this will attempt
            to guess their gender using it and fill that into the database (and then other
            caches)

    Returns:
        (GenderWithSource): The gender of the user, or unknown if
            we found an identifier we were satisfied with but it was still
            unhelpful, e.g., names that are used equally often for male and
            female babies. We also return `unknown` if we are temporarily unable
            to guess due to excessive errors while connecting with
            gender-api.com and no name is set

    Raises:
        GenderByUserUserNotFoundError: if the user doesn't appear to exist
        GenderByUserNotSetError: if only_if_set is True but the user does not have a gender
            set
        lib.gender.api.GenderAPIError: if there was an HTTP error connecting to gender-api.com
            (e.g., a 500 status code). Not used for e.g. connection errors
        aiohttp.ClientError: if there was a connection error connecting to gender-api.com
        pydantic.ValidationError: if the response from gender-api.com didn't match what we
            expected
    """
    req_id = secrets.token_urlsafe(4)
    logger.debug(
        f"get_gender_by_user assigned {req_id} for {sub=}, {locale=}, {only_if_set=}"
    )
    raw = await _get_gender_from_local_cache(itgs, sub=sub)
    if raw is not None:
        logger.debug(f"  -> {req_id} LOCAL CACHE HIT")
        return _convert_from_stored(raw)

    raw = await _get_gender_from_remote_cache(itgs, sub=sub)
    if raw is not None:
        logger.debug(f"  -> {req_id} REMOTE CACHE HIT")
        await _set_gender_in_local_cache(itgs, sub=sub, raw=raw)
        return _convert_from_stored(raw)

    # none consistency is _mostly_ sufficient here because if it were modified recently
    # it would be in one of the caches. i think in theory this could overwrite a cached
    # more recent value though, which we could handle with created_at checks as the difference
    # would need probably be substantial, i.e., more than clock drift
    parsed = await _get_gender_from_database(itgs, sub=sub, read_consistency="none")
    if parsed is not None:
        logger.debug(f"  -> {req_id} DB HIT")
        await purge_gender_by_user_cache(itgs, sub=sub, fill=parsed)
        return parsed

    logger.debug(f"  -> {req_id} MISS")
    if only_if_set:
        raise GenderByUserNotSetError(sub)

    redis = await itgs.redis()

    subscriptions = gender_subscriptions_by_sub.get(sub)
    if subscriptions is None:
        subscriptions = []
        gender_subscriptions_by_sub[sub] = subscriptions

    data_event = asyncio.Event()
    subscriptions.append(data_event)

    locked = await redis.set(_lock_key(sub), b"1", nx=True, ex=20)
    logger.debug(f"  -> {req_id} lock attempt: {locked=}")
    raw = await _get_gender_from_local_cache(itgs, sub=sub)
    if raw is not None:
        logger.debug(f"  -> {req_id} LOCAL CACHE HIT (post-lock A)")
        subscriptions.remove(data_event)
        if not subscriptions and gender_subscriptions_by_sub.get(sub) is subscriptions:
            gender_subscriptions_by_sub.pop(sub)
        if locked:
            await redis.delete(_lock_key(sub))
        return _convert_from_stored(raw)

    if not locked:
        timedout = False
        try:
            logger.debug(f"  -> {req_id} waiting for data event")
            await asyncio.wait_for(data_event.wait(), timeout=3)
            logger.debug(f"  -> {req_id} received data event")
        except asyncio.TimeoutError:
            await handle_warning(
                f"{__name__}:timeout",
                f"Timed out waiting for lock on {sub}'s gender info to be released",
            )
            subscriptions.remove(data_event)
            if (
                not subscriptions
                and gender_subscriptions_by_sub.get(sub) is subscriptions
            ):
                gender_subscriptions_by_sub.pop(sub)
            timedout = True

        raw = await _get_gender_from_local_cache(itgs, sub=sub)
        if raw is not None:
            logger.debug(f"  -> {req_id} LOCAL CACHE HIT (post-lock B)")
            return _convert_from_stored(raw)

        if not timedout:
            await handle_warning(
                f"{__name__}:nodata",
                f"Got no data for {sub}'s gender despite just receiving data event",
            )
    else:
        subscriptions.remove(data_event)
        if not subscriptions and gender_subscriptions_by_sub.get(sub) is subscriptions:
            gender_subscriptions_by_sub.pop(sub)

    # have to recheck with the lock
    raw = await _get_gender_from_remote_cache(itgs, sub=sub)
    if raw is not None:
        logger.debug(f"  -> {req_id} REMOTE CACHE HIT (post-lock)")
        await _set_gender_in_local_cache(itgs, sub=sub, raw=raw)
        if locked:
            await redis.delete(_lock_key(sub))
        return _convert_from_stored(raw)

    parsed = await _get_gender_from_database(itgs, sub=sub, read_consistency="weak")
    if parsed is not None:
        logger.debug(f"  -> {req_id} DB HIT (post-lock)")
        await purge_gender_by_user_cache(itgs, sub=sub, fill=parsed)
        if locked:
            await redis.delete(_lock_key(sub))
        return parsed

    if await is_gender_api_outage(itgs):
        await handle_warning(
            f"{__name__}:api_outage",
            f"Excessive errors connecting to gender-api.com; guessing disabled for `{sub=}`",
        )
        parsed = GenderWithSource(
            gender="unknown",
            source=GenderByFallbackSource(type="by-fallback"),
        )
        await purge_gender_by_user_cache(itgs, sub=sub, fill=parsed)
        if locked:
            await redis.delete(_lock_key(sub))
        return parsed

    identifiers = await _get_identifiers_from_database(
        itgs, sub=sub, read_consistency="strong"
    )
    if identifiers is None or not identifiers.is_useful():
        if os.environ["ENVIRONMENT"] != "dev":
            await handle_warning(
                f"{__name__}:no_useful_identifiers",
                f"found no useful identifiers for `{sub=}`",
            )
        parsed = GenderWithSource(
            gender="unknown", source=GenderByFallbackSource(type="by-fallback")
        )
        _, active = await _try_set_gender_in_database(itgs, sub=sub, parsed=parsed)
        await purge_gender_by_user_cache(itgs, sub=sub, fill=active)
        return active

    try:
        logger.debug(f"  -> {req_id} GUESSING with {identifiers=}, {locale=}")
        guessed = await _guess_using_api(itgs, identifiers=identifiers, locale=locale)
        logger.debug(f"  -> {req_id} GUESSED {guessed=}")
    except Exception as e:
        await record_gender_api_error(itgs)
        await handle_error(e, extra_info=f"{identifiers=}, {locale=}")
        guessed = None

    if guessed is None:
        await handle_warning(
            f"{__name__}:guess_failed",
            f"failed to guess gender for `{sub=}` using\n\n```\n{identifiers!r}\n```",
        )
        guessed = GenderWithSource(
            gender="unknown", source=GenderByFallbackSource(type="by-fallback")
        )

    _, active = await _try_set_gender_in_database(itgs, sub=sub, parsed=guessed)
    logger.debug(f"  -> {req_id} TRY-SET {parsed=} became {active=}")
    await purge_gender_by_user_cache(itgs, sub=sub, fill=active)
    await redis.delete(_lock_key(sub))
    return active


async def purge_gender_by_user_cache(
    itgs: Itgs, /, *, sub: str, fill: Optional[GenderWithSource]
) -> None:
    """Purges the instance and redis gender caches for the user with the given sub.
    This is meant to be called when the user sets their gender manually, or an admin
    sets their gender for them (e.g., in response to a support request)

    Args:
        itgs (Itgs): the integrations to (re)use
        sub (str): the sub of the user whose gender may have changed outside of
            a `get_gender_by_user` call.
        fill (GenderWithSource, None): the data to fill in the caches, or None to
            have it refetched on the next call
    """

    if fill:
        raw = _convert_to_stored(fill)
        cache = await itgs.local_cache()
        cache.set(
            _cache_key(sub), raw, expire=3600 + random.randint(1, 10), tag="collab"
        )

        redis = await itgs.redis()
        async with redis.pipeline() as pipe:
            pipe.multi()
            await pipe.set(_cache_key(sub), raw)
            await pipe.publish(
                _pubsub_key,
                _format_pubsub_fill_message(PubSubFillMessage(sub=sub, raw=raw)),
            )
            await pipe.execute()
    else:
        try:
            redis = await itgs.redis()
            await redis.delete(_cache_key(sub))
        finally:
            cache = await itgs.local_cache()
            cache.delete(_cache_key(sub))

        redis = await itgs.redis()
        await redis.publish(
            _pubsub_key, _format_pubsub_purge_message(PubSubPurgeMessage(sub=sub))
        )


async def is_gender_api_outage(itgs: Itgs, /) -> bool:
    """Determines if we are currently experiencing difficulties getting useful
    responses from gender-api.com. This does not generally need to be called
    directly, as it is handled by `get_gender_by_user`

    Args:
        itgs (Itgs): the integrations to (re)use

    Returns:
        bool: True if we have reached the watermark for errors in the last 20
            minutes
    """
    num_recent_errors = await zcard_exact_window_safe(
        itgs, b"gender_api:errors", int(time.time() - 60 * 20)
    )
    return num_recent_errors >= 10


async def record_gender_api_error(itgs: Itgs, /) -> None:
    """Records an error just occurred getting a useful response from gender-api.com,
    in order to potentially trigger `is_gender_api_outage`

    Args:
        itgs (Itgs): the integrations to (re)use
    """
    await zadd_exact_window_safe(
        itgs, b"gender_api:errors", b"gender_api:errors:idcounter", int(time.time())
    )


@lifespan_handler
async def _handle_incoming_messages_forever():
    task = asyncio.create_task(_handle_incoming_messages())
    yield


async def _handle_incoming_messages() -> None:
    assert pps.instance is not None

    try:
        async with pps.PPSSubscription(
            pps.instance,
            "ps:users:gender",
            "l_g_bu_him",
        ) as sub:
            async for raw_message_bytes in sub:
                parsed = _parse_pubsub_message(raw_message_bytes)
                async with Itgs() as itgs:
                    cache = await itgs.local_cache()
                    if isinstance(parsed, PubSubPurgeMessage):
                        cache.delete(_cache_key(parsed.sub))
                    else:
                        cache.set(
                            _cache_key(parsed.sub),
                            parsed.raw,
                            expire=3600 + random.randint(1, 10),
                            tag="collab",
                        )

                        listeners = gender_subscriptions_by_sub.pop(parsed.sub, [])
                        for event in listeners:
                            event.set()
    except Exception as e:
        if pps.instance.exit_event.is_set() and isinstance(e, pps.PPSShutdownException):
            return
        await handle_error(e)
    finally:
        print("lib.gender.by_user cache push loop exiting")


async def _get_gender_from_local_cache(itgs: Itgs, /, *, sub: str) -> Optional[bytes]:
    """Fetches the raw stored GenderWithSource for the user with the given
    sub from the local cache (disk)

    Args:
        itgs (Itgs): the integrations to (re)use
        sub (str): the sub of the user whose gender to fetch

    Returns:
        (bytes, None): the stored data for the user, if any, otherwise None
    """
    cache = await itgs.local_cache()
    return cast(Optional[bytes], cache.get(_cache_key(sub)))


async def _set_gender_in_local_cache(itgs: Itgs, /, *, sub: str, raw: bytes) -> None:
    """Writes the given raw GenderWithSource for the user with the given sub to
    the local cache (disk)

    Args:
        itgs (Itgs): the integrations to (re)use
        sub (str): the sub of the user whose gender to write
        raw (bytes): the raw data to write
    """
    cache = await itgs.local_cache()
    cache.set(_cache_key(sub), raw, expire=3600 + random.randint(1, 10), tag="collab")


async def _get_gender_from_remote_cache(itgs: Itgs, /, *, sub: str) -> Optional[bytes]:
    """Fetches the raw stored GenderWithSource for the user with the given sub
    from the remote cache (redis)

    Args:
        itgs (Itgs): the integrations to (re)use
        sub (str): the sub of the user whose gender to fetch

    Returns:
        (bytes, None): the stored data for the user, if any, otherwise None
    """
    return await (await itgs.redis()).get(_cache_key(sub))


async def _get_gender_from_database(
    itgs: Itgs, /, *, sub: str, read_consistency: Literal["none", "weak", "strong"]
) -> Optional[GenderWithSource]:
    """Fetches the gender we have for the user in the database, if any, at
    the given consistency.

    Args:
        itgs (Itgs): the integrations to (re)use
        sub (str): the sub of the user whose active gender to fetch
        read_consistency (Literal["none", "weak", "strong"]): the consistency
            level to use when reading from the database

    Returns:
        GenderWithSource, None: the active gender for the user, if any, otherwise None.
            None does not imply the user does not exist.
    """
    conn = await itgs.conn()
    cursor = conn.cursor(read_consistency)
    response = await cursor.execute(
        "SELECT user_genders.gender, user_genders.source FROM users, user_genders "
        "WHERE users.sub = ? AND users.id = user_genders.user_id AND user_genders.active",
        (sub,),
    )
    if not response.results:
        return None
    gender = cast(Gender, response.results[0][0])
    source = gender_source_adapter.validate_json(cast(str, response.results[0][1]))
    return GenderWithSource(gender=gender, source=source)


async def _try_set_gender_in_database(
    itgs: Itgs, /, *, sub: str, parsed: GenderWithSource
) -> Tuple[bool, GenderWithSource]:
    """Attempts to store the given GenderWithSource for the user with the given
    sub, if they do not already have an active GenderWithSource, otherwise returns
    the active GenderWithSource.

    Args:
        itgs (Itgs): the integrations to (re)use
        sub (str): the sub of the user
        parsed (GenderWithSource): the gender with source to store

    Returns:
        (bool, GenderWithSource): a tuple of (success, active) where success is True
            if we saved the provided GenderWithSource and False if we did not, and
            active is the users active GenderWithSource.
    """
    conn = await itgs.conn()
    cursor = conn.cursor("strong")

    response = await cursor.executeunified3(
        (
            (
                "INSERT INTO user_genders (uid, user_id, gender, source, active, created_at) "
                "SELECT"
                " ?, users.id, ?, ?, 1, ? "
                "FROM users "
                "WHERE"
                " users.sub = ?"
                " AND NOT EXISTS ("
                "  SELECT 1 FROM user_genders AS ug"
                "  WHERE ug.user_id = users.id AND ug.active"
                " )",
                (
                    f"oseh_ug_{secrets.token_urlsafe(16)}",
                    parsed.gender,
                    parsed.source.model_dump_json(),
                    time.time(),
                    sub,
                ),
            ),
            (
                "SELECT user_genders.gender, user_genders.source FROM users, user_genders "
                "WHERE users.sub = ? AND users.id = user_genders.user_id AND user_genders.active",
                (sub,),
            ),
        )
    )

    success = response[0].rows_affected is not None and response[0].rows_affected > 0
    assert response[1].results, response
    gender = cast(Gender, response[1].results[0][0])
    source = gender_source_adapter.validate_json(cast(str, response[1].results[0][1]))
    active = GenderWithSource(gender=gender, source=source)
    return (success, active)


@dataclass
class IdentifiersFromDatabase:
    given_name: Optional[str]
    family_name: Optional[str]
    verified_emails: List[str]
    unverified_emails: List[str]
    timezone: Optional[str]

    def is_useful(self) -> bool:
        return (
            self.given_name is not None
            or bool(self.verified_emails)
            or bool(self.unverified_emails)
        )


async def _get_identifiers_from_database(
    itgs: Itgs, /, *, sub: str, read_consistency: Literal["none", "weak", "strong"]
) -> Optional[IdentifiersFromDatabase]:
    """Fetches identifiers for the user with the given sub from the database, if
    the user is in the database, at the given consistency.

    Args:
        itgs (Itgs): the integrations to (re)use
        sub (str): the sub of the user whose identifiers to fetch
        read_consistency (Literal["none", "weak", "strong"]): the consistency
            level to use when reading from the database

    Returns:
        IdentifiersFromDatabase, None: the identifiers for the user, if any, otherwise
            None. None implies the user does not exist, whereas a result with no
            filled fields implies the user exists but has no useful identifiers.
    """
    conn = await itgs.conn()
    cursor = conn.cursor(read_consistency)
    response = await cursor.executeunified3(
        (
            ("SELECT given_name, family_name, timezone FROM users WHERE sub=?", (sub,)),
            (
                "SELECT user_email_addresses.email, user_email_addresses.verified "
                "FROM users, user_email_addresses "
                "WHERE users.sub = ? AND user_email_addresses.user_id = users.id "
                "ORDER BY"
                " user_email_addresses.verified DESC,"
                " user_email_addresses.created_at ASC,"
                " user_email_addresses.id",
                (sub,),
            ),
        )
    )
    if not response[0].results:
        assert not response[1].results, response
        return None

    given_name = cast(Optional[str], response[0].results[0][0])
    family_name = cast(Optional[str], response[0].results[0][1])
    timezone = cast(Optional[str], response[0].results[0][2])

    if given_name is not None:
        normalized = given_name.strip().lower()
        if normalized.startswith("guest") or normalized.startswith("anon"):
            given_name = None
            family_name = None

    emails = cast(List[Tuple[str, int]], response[1].results)
    email_idx = 0

    verified_emails: List[str] = []

    while email_idx < len(emails) and emails[email_idx][1]:
        verified_emails.append(emails[email_idx][0])
        email_idx += 1

    unverified_emails: List[str] = []

    while email_idx < len(emails):
        unverified_emails.append(emails[email_idx][0])
        email_idx += 1

    verified_emails = _remove_relays(verified_emails)
    unverified_emails = _remove_relays(unverified_emails)

    return IdentifiersFromDatabase(
        given_name=given_name,
        family_name=family_name,
        verified_emails=verified_emails,
        unverified_emails=unverified_emails,
        timezone=timezone,
    )


def _remove_relays(emails: List[str]) -> List[str]:
    """Removes known relays or otherwise unhelpful email addresses"""
    return [
        e
        for e in emails
        if not e.endswith("@privaterelay.appleid.com") and not e.startswith("guest-")
    ]


async def _guess_using_api(
    itgs: Itgs, /, *, identifiers: IdentifiersFromDatabase, locale: Optional[str]
) -> Optional[GenderWithSource]:
    """Guesses the gender of the user from the given identifiers and locale. If
    a locale is not specified but a timezone is available, this will attempt to
    convert the timezone into a locale and use that as a hint for guessing the
    gender.

    Args:
        itgs (Itgs): the integrations to (re)use
        identifiers (IdentifiersFromDatabase): the identifiers for the user
        locale (Optional[str]): the locale of the user, as an IETF BCP 47 language tag,
            e.g., en-US. May use underscores instead of dashes as a separator. Improves
            the accuracy of guesses, but is not required. If not available, we will try
            to use the timezone associated with the user to guess a locale.

    Returns:
        GenderSource, None: the guessed gender for the user, or None if one could not
            be determined
    """
    if locale is None and identifiers.timezone is not None:
        locale = _locale_from_timezone(identifiers.timezone)

    if identifiers.given_name is not None:
        result = await (await itgs.gender_api()).query_by_first_name(
            identifiers.given_name, locale=locale
        )
        if result.response.result_found and result.response.gender is not None:
            return GenderWithSource(
                gender=result.response.gender,
                source=GenderByFirstNameSource(
                    type="by-first-name",
                    url=result.url,
                    payload=result.payload,
                    response=result.response,
                ),
            )

    for email in itertools.chain(
        identifiers.verified_emails, identifiers.unverified_emails
    ):
        result = await (await itgs.gender_api()).query_by_email_address(
            email, locale=locale
        )
        if result.response.result_found and result.response.gender is not None:
            return GenderWithSource(
                gender=result.response.gender,
                source=GenderByEmailAddressSource(
                    type="by-email-address",
                    url=result.url,
                    payload=result.payload,
                    response=result.response,
                ),
            )

    return None


def _locale_from_timezone(timezone: str) -> Optional[str]:
    """Converts a timezone into a locale, if possible"""
    # I just looked at our database and sorted by descending count to decide which
    # ones to include here.
    if timezone.startswith("America/") or timezone.startswith("US/"):
        return "en-US"
    if timezone == "Europe/Berlin":
        return "de-DE"
    if timezone == "Europe/London":
        return "en-GB"
    if timezone == "Europe/Paris":
        return "fr-FR"
    if timezone == "Pacific/Honolulu":
        return "en-US"

    return None


@dataclass
class PubSubPurgeMessage:
    sub: str


@dataclass
class PubSubFillMessage:
    sub: str
    raw: bytes


def _convert_to_stored(value: GenderWithSource) -> bytes:
    return value.__pydantic_serializer__.to_json(value)


def _convert_from_stored(raw: bytes) -> GenderWithSource:
    return GenderWithSource.model_validate_json(raw)


def _format_pubsub_purge_message(msg: PubSubPurgeMessage) -> bytes:
    encoded_sub = msg.sub.encode("utf-8")

    raw = io.BytesIO()
    raw.write((0).to_bytes(1, "big"))
    raw.write(len(encoded_sub).to_bytes(2, "big"))
    raw.write(encoded_sub)
    return raw.getvalue()


def _format_pubsub_fill_message(msg: PubSubFillMessage) -> bytes:
    encoded_sub = msg.sub.encode("utf-8")

    raw = io.BytesIO()
    raw.write((1).to_bytes(1, "big"))
    raw.write(len(encoded_sub).to_bytes(2, "big"))
    raw.write(encoded_sub)
    raw.write(len(msg.raw).to_bytes(8, "big"))
    raw.write(msg.raw)
    return raw.getvalue()


def _parse_pubsub_message(raw: bytes) -> Union[PubSubPurgeMessage, PubSubFillMessage]:
    reader = io.BytesIO(raw)
    is_fill = reader.read(1)[0] == 1
    sub_len = int.from_bytes(reader.read(2), "big")
    sub = reader.read(sub_len).decode("utf-8")
    if not is_fill:
        return PubSubPurgeMessage(sub=sub)

    raw_len = int.from_bytes(reader.read(8), "big")
    return PubSubFillMessage(sub=sub, raw=reader.read(raw_len))


def _cache_key(sub: str) -> bytes:
    return f"users:gender:{sub}".encode("utf-8")


def _lock_key(sub: str) -> bytes:
    return f"users:gender:{sub}:lock".encode("utf-8")


_pubsub_key = b"ps:users:gender"


if __name__ == "__main__":

    async def _main():
        sub = input("Enter user sub: ").strip()
        locale = input("Enter locale (or leave blank): ").strip()
        if locale == "":
            locale = None
        async with Itgs() as itgs:
            result = await get_gender_by_user(itgs, sub=sub, locale=locale)
            print(f"{result=}")

    asyncio.run(_main())
