import json
import secrets
from typing import Any, List, Optional, Tuple
from error_middleware import handle_contextless_error
from itgs import Itgs
from dataclasses import dataclass
import time


@dataclass
class EmotionChoiceInfo:
    """Describes information that is presented to the user after they select
    a feeling.
    """

    word: str
    """The word they selected."""

    votes_for_word: int
    """How many times that word has been selected (recently). Note this is the
    quantity we are reporting to users, which is not necessarily the same as
    the real quantity of votes for that word.
    """

    votes_total: int
    """How many times any feeling has been selected (recently). Note this is 
    the quantity we are reporting to users, which is not necessarily the same as
    the real quantity of votes for that word.
    """

    checked_at: float
    """When this information was retrieved"""


async def get_emotion_choice_information(itgs: Itgs, *, word: str) -> EmotionChoiceInfo:
    """Retrieves how many votes we're tellign users have occurred for the given
    emotion word recently. This is initially fudged so that there are generally
    double-digit votes in all categories, then it goes up normally.

    Args:
        itgs (Itgs): The integrations to (re)use
        word (str): The emotion word to retrieve information for

    Returns:
        EmotionChoiceInfo: The information about the emotion word
    """
    redis = await itgs.redis()

    result = await redis.hmget(
        b"emotion_users:choices", word.encode("utf-8"), b"__total"
    )

    votes_for_word = int(result[0]) if result[0] is not None else 0
    votes_total = int(result[1]) if result[1] is not None else 0

    return EmotionChoiceInfo(
        word=word,
        votes_for_word=votes_for_word,
        votes_total=votes_total,
        checked_at=time.time(),
    )


@dataclass
class OnChooseWordResult:
    emotion_user_uid: str
    """The row of the newly creation emotion/user record"""


async def on_choose_word(
    itgs: Itgs,
    *,
    word: str,
    user_sub: str,
    journey_uid: str,
    replaced_emotion_user_uid: Optional[str] = None,
) -> OnChooseWordResult:
    """Should be called whenever a user selects a particular word, in order
    to update our external statistics.

    Args:
        itgs (Itgs): The integrations to (re)use
        word (str): The word the user selected
        user_sub (str): The user's sub
    """
    redis = await itgs.redis()
    key = b"emotion_users:choices"

    async with redis.pipeline(transaction=True) as pipe:
        pipe.multi()
        await pipe.hincrby(key, word.encode("utf-8"), 1)
        await pipe.hincrby(key, b"__total", 1)
        await pipe.execute()

    conn = await itgs.conn()
    cursor = conn.cursor()

    emotion_user_uid = f"oseh_eu_{secrets.token_urlsafe(16)}"

    now = time.time()
    queries: List[Tuple[str, List[Any]]] = [
        (
            """
            INSERT INTO emotion_users (
                uid, user_id, emotion_id, journey_id, status, created_at
            )
            SELECT
                ?, users.id, emotions.id, journeys.id, ?, ?
            FROM users, emotions, journeys
            WHERE
                users.sub = ?
                AND emotions.word = ?
                AND journeys.uid = ?
            """,
            (
                emotion_user_uid,
                json.dumps({"type": "selected"}),
                now,
                user_sub,
                word,
                journey_uid,
            ),
        )
    ]

    if replaced_emotion_user_uid is not None:
        queries.append(
            (
                """
                UPDATE emotion_users
                SET status=?
                WHERE
                    uid = ?
                    AND json_extract(status, '$.type') = 'selected'
                    AND EXISTS (
                        SELECT 1 FROM users
                        WHERE 
                            users.id = emotion_users.user_Id
                            AND users.sub = ?
                    )
                """,
                (
                    json.dumps(
                        {
                            "type": "replaced",
                            "replaced_at": now,
                            "replaced_with": emotion_user_uid,
                        }
                    ),
                    replaced_emotion_user_uid,
                    user_sub,
                ),
            )
        )

    response = await cursor.executemany3(queries)
    if response[0].rows_affected is None or response[0].rows_affected < 1:
        await handle_contextless_error(
            extra_info=f"failed to insert into emotion_users {user_sub=}, {word=}, {journey_uid=}"
        )
    if replaced_emotion_user_uid is not None and (
        response[1].rows_affected is None or response[1].rows_affected < 1
    ):
        await handle_contextless_error(
            extra_info=f"failed to update emotion_users {replaced_emotion_user_uid=}, {user_sub=}"
        )
    return OnChooseWordResult(emotion_user_uid=emotion_user_uid)


async def on_started_emotion_user_journey(
    itgs: Itgs, *, emotion_user_uid: str, user_sub: str
) -> None:
    """Tracks that the user with the given sub has actually started the journey
    association with the emotion/user relationship with the given uid.

    Args:
        itgs (Itgs): the integrations to (re)use
        emotion_user_uid (str): the uid of the emotion/user relationship
        user_sub (str): the sub of the user
    """
    conn = await itgs.conn()
    cursor = conn.cursor()

    user_journey_uid = f"oseh_uj_{secrets.token_urlsafe(16)}"
    now = time.time()

    response = await cursor.executemany3(
        (
            (
                """
            UPDATE emotion_users
            SET status = ?
            WHERE
                uid = ?
                AND json_extract(status, '$.type') = 'selected'
                AND EXISTS (
                    SELECT 1 FROM users
                    WHERE
                        users.id = emotion_users.user_id
                        AND users.sub = ?
                )
            """,
                (
                    json.dumps({"type": "joined", "joined_at": now}),
                    emotion_user_uid,
                    user_sub,
                ),
            ),
            (
                """
            INSERT INTO user_journeys (
                uid, user_id, journey_id, created_at
            )
            SELECT
                ?, users.id, emotion_users.journey_id, ?
            FROM emotion_users, users
            WHERE
                emotion_users.uid = ?
                AND users.id = emotion_users.user_id
                AND users.sub = ?
            """,
                (
                    user_journey_uid,
                    now,
                    emotion_user_uid,
                    user_sub,
                ),
            ),
        )
    )
    if response[0].rows_affected is None or response[0].rows_affected < 1:
        await handle_contextless_error(
            extra_info=f"failed to update emotion_users to joined; {emotion_user_uid=}, {user_sub=}"
        )
    if response[1].rows_affected is None or response[1].rows_affected < 1:
        await handle_contextless_error(
            extra_info=f"failed to insert into user_journeys; {emotion_user_uid=}, {user_sub=}"
        )


async def get_emotion_pictures(itgs: Itgs, *, word: str) -> List[str]:
    """Retrieves the image file uid of pictures of people who have selected
    the given word recently. If there aren't enough real people to get images
    of, we add in a few fake ones.

    This will attempt to fetch from the nearest cache, filling it from the next
    nearest source if it's not available.

    Since this isn't excessively expensive, this does not include cache stampede
    mitigation, meaning that multiple instances might attempt to fill the cache
    at the same time.

    Args:
        itgs (Itgs): The integrations to (re)use
        word (str): The word to retrieve pictures for

    Returns:
        list[str]: The image file uids of the pictures
    """
    result = await get_emotion_pictures_from_cache(itgs, word=word)
    if result is not None:
        return result

    result = await get_emotion_pictures_from_redis(itgs, word=word)
    if result is not None:
        raw = json.dumps(result).encode("utf-8")
        await set_emotion_pictures_in_cache(itgs, word=word, raw=raw)
        return result

    result = await get_emotion_pictures_from_db(itgs, word=word)
    raw = json.dumps(result).encode("utf-8")
    await set_emotion_pictures_in_redis(itgs, word=word, raw=raw)
    await set_emotion_pictures_in_cache(itgs, word=word, raw=raw)
    return result


async def set_emotion_pictures_in_cache(itgs: Itgs, *, word: str, raw: bytes) -> None:
    """Stores the given emotion pictures in the local cache.

    Args:
        itgs (Itgs): The integrations to (re)use
        word (str): The word to store pictures for
        raw (bytes): The raw data to store, as a json serialization of a list of
            image file uids.
    """
    cache = await itgs.local_cache()
    key = f"emotion_users:pictures:{word}".encode("utf-8")
    cache.set(key, raw, expire=600, tag="collab")


async def get_emotion_pictures_from_cache(
    itgs: Itgs, *, word: str
) -> Optional[List[str]]:
    """Retrieves the image file uid of pictures of people who have selected
    the given word recently, from the local cache, if available

    Args:
        itgs (Itgs): The integrations to (re)use
        word (str): The word to retrieve pictures for
    """
    cache = await itgs.local_cache()
    key = f"emotion_users:pictures:{word}".encode("utf-8")
    raw = cache.get(key)
    if raw is None:
        return None
    return json.loads(raw)


async def set_emotion_pictures_in_redis(itgs: Itgs, *, word: str, raw: bytes) -> None:
    """Stores the given emotion pictures in redis.

    Args:
        itgs (Itgs): The integrations to (re)use
        word (str): The word to store pictures for
        raw (bytes): The raw data to store, as a json serialization of a list of
            image file uids.
    """
    key = f"emotion_users:pictures:{word}".encode("utf-8")
    redis = await itgs.redis()
    await redis.set(key, raw, ex=600)


async def get_emotion_pictures_from_redis(
    itgs: Itgs, *, word: str
) -> Optional[List[str]]:
    """Retrieves the image file uid of pictures of people who have selected
    the given word recently, from redis, if available

    Args:
        itgs (Itgs): The integrations to (re)use
        word (str): The word to retrieve pictures for

    Returns:
        list[str] or None: The image file uids of the pictures, or None if it's
            not available in the cache
    """
    key = f"emotion_users:pictures:{word}".encode("utf-8")
    redis = await itgs.redis()
    raw = await redis.get(key)
    if raw is None:
        return None
    return json.loads(raw)


async def get_emotion_pictures_from_db(itgs: Itgs, *, word: str) -> List[str]:
    """Retrieves the image file uid of pictures of people who have selected
    the given word recently. If there aren't enough real people to get images
    of, we add in a few fake ones.

    Args:
        itgs (Itgs): The integrations to (re)use
        word (str): The word to retrieve pictures for

    Returns:
        list[str]: The image file uids of the pictures
    """
    conn = await itgs.conn()
    cursor = conn.cursor("none")

    autofill_user_emails = [
        "fhfv9dmgqq@privaterelay.appleid.com",  # Shamim
        "tj@oseh.com",
        "paul@oseh.com",
        "ashley@oseh.com",
        "kgatz14@gmail.com",
    ]
    autofill_user_qmarks = "(" + ",".join(["?"] * len(autofill_user_emails)) + ")"

    responded_since = time.time() - 60 * 60 * 24 * 7
    response = await cursor.execute(
        f"""
        SELECT
            image_files.uid
        FROM image_files
        WHERE
            EXISTS (
                SELECT 1 FROM user_profile_pictures
                WHERE
                    user_profile_pictures.image_file_id = image_files.id
                    AND user_profile_pictures.latest = 1
                    AND (
                        EXISTS (
                            SELECT 1 FROM emotions, emotion_users
                            WHERE 
                                emotions.word = ?
                                AND emotions.id = emotion_users.emotion_id
                                AND emotion_users.user_id = user_profile_pictures.user_id
                                AND emotion_users.created_at > ?
                        )
                        OR EXISTS (
                            SELECT 1 FROM user_email_addresses
                            WHERE 
                                user_email_addresses.user_id = user_profile_pictures.user_id
                                AND user_email_addresses.email IN {autofill_user_qmarks}
                        )
                    )
            )
        LIMIT 5
        """,
        (word, responded_since, *autofill_user_emails),
    )

    return [row[0] for row in (response.results or [])]
