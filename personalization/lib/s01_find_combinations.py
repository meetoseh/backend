"""This module is responsible for the first step for personalizing content after
a user picks an emotion: determining what instructor/category combinations are
available for a given emotion, and what their biases are.
"""
from typing import Dict, List, Optional
from itgs import Itgs
from dataclasses import dataclass
import io
import json
import socket
import hashlib

from journeys.models.series_flags import SeriesFlags


_hasher = hashlib.new("md5", usedforsecurity=False)
_hasher.update(socket.gethostname().encode("utf-8"))
_cache_offset = _hasher.digest()[0]
del _hasher
DISKCACHE_CACHE_TIME_SECONDS = 60 * 4 + 15 + _cache_offset
"""The amount of time to cache the instructor/category biases in diskcache. We
add a stable device-specific random component to reduce thundering herd
problems.
"""

REDIS_CACHE_TIME_SECONDS = 60 * 17
"""The amount of time to cache the instructor/category biases in redis."""


@dataclass
class InstructorCategoryAndBias:
    """An instructor, subcategory, and the corresponding biases. From context
    an emotion word is also present.
    """

    instructor_uid: str
    """The uid of the instructor"""
    instructor_name: str
    """The name of the instructor"""
    instructor_bias: float
    """The bias for the instructor"""
    category_uid: str
    """The uid of the category"""
    category_internal_name: str
    """The internal name of the category"""
    category_bias: float
    """The bias for the category"""


async def get_instructor_category_and_biases(
    itgs: Itgs, *, emotion: str
) -> List[InstructorCategoryAndBias]:
    """Returns all the instructor, category, bias combinations that are available
    for the emotion with the given word.
    """

    # PERF: This is, in theory, a good candidate for smart caching: it changes
    # rarely, so we could get away with a very long cache time with smart cache
    # invalidation. However, that seems really challenging, so for now I just do
    # a basic time-based 2-layer cache and using read replicas.

    value = await get_instructor_category_and_biases_from_local_cache(
        itgs, emotion=emotion
    )
    if value is not None:
        return deserialize_for_caches(value)

    value = await get_instructor_category_and_biases_from_redis(itgs, emotion=emotion)
    if value is not None:
        await set_instructor_category_and_biases_in_local_cache(
            itgs, emotion=emotion, serialized=value
        )
        return deserialize_for_caches(value)

    parsed = await get_instructor_category_and_biases_from_db(itgs, emotion=emotion)
    value = serialize_for_caches(parsed)
    await set_instructor_category_and_biases_in_local_cache(
        itgs, emotion=emotion, serialized=value
    )
    await set_instructor_category_and_biases_in_redis(
        itgs, emotion=emotion, serialized=value
    )
    return parsed


def serialize_for_caches(arr: List[InstructorCategoryAndBias]) -> bytes:
    """Serializes the given list so that it can be stored efficiently in the cache
    and deserialized using deserialize_for_caches.
    """
    raw = io.BytesIO()
    raw.write(b"[")

    # Instructor lookup
    raw.write(b"[")
    instructor_to_idx: Dict[str, int] = dict()
    for item in arr:
        if item.instructor_uid in instructor_to_idx:
            continue
        if len(instructor_to_idx) > 0:
            raw.write(b",")
        instructor_to_idx[item.instructor_uid] = len(instructor_to_idx)
        raw.write(
            json.dumps(
                [item.instructor_uid, item.instructor_name, item.instructor_bias]
            ).encode("utf-8")
        )
    raw.write(b"],")

    # Category lookup
    raw.write(b"[")
    category_to_idx: Dict[str, int] = dict()
    for item in arr:
        if item.category_uid in category_to_idx:
            continue
        if len(category_to_idx) > 0:
            raw.write(b",")
        category_to_idx[item.category_uid] = len(category_to_idx)
        raw.write(
            json.dumps(
                [item.category_uid, item.category_internal_name, item.category_bias]
            ).encode("utf-8")
        )
    raw.write(b"],")

    # Items
    raw.write(b"[")
    for idx, item in enumerate(arr):
        if idx > 0:
            raw.write(b",")

        raw.write(
            json.dumps(
                [
                    instructor_to_idx[item.instructor_uid],
                    category_to_idx[item.category_uid],
                ]
            ).encode("utf-8")
        )
    raw.write(b"]]")

    return raw.getvalue()


def deserialize_for_caches(raw: bytes) -> List[InstructorCategoryAndBias]:
    """Undoes the operation of serialize_for_caches"""
    instructors_by_idx, categories_by_idx, items = json.loads(raw)

    result: List[InstructorCategoryAndBias] = []
    for instructor_idx, category_idx in items:
        instructor = instructors_by_idx[instructor_idx]
        category = categories_by_idx[category_idx]
        result.append(
            InstructorCategoryAndBias(
                instructor_uid=instructor[0],
                instructor_name=instructor[1],
                instructor_bias=instructor[2],
                category_uid=category[0],
                category_internal_name=category[1],
                category_bias=category[2],
            )
        )

    return result


async def get_instructor_category_and_biases_from_local_cache(
    itgs: Itgs, *, emotion: str
) -> Optional[bytes]:
    """Fetches the serialized instructor category biases for the given emotion
    from the local cache, if they exist.
    """
    cache = await itgs.local_cache()
    result = cache.get(
        f"personalization:instructor_category_biases:{emotion}".encode("utf-8")
    )
    if result is None:
        return None
    assert isinstance(result, bytes), type(result)
    return result


async def set_instructor_category_and_biases_in_local_cache(
    itgs: Itgs, *, emotion: str, serialized: bytes
) -> None:
    """Writes the serialized instructor category biases for the given emotion
    to the local cache.
    """
    cache = await itgs.local_cache()
    cache.set(
        f"personalization:instructor_category_biases:{emotion}".encode("utf-8"),
        serialized,
        expire=REDIS_CACHE_TIME_SECONDS,
    )


async def get_instructor_category_and_biases_from_redis(
    itgs: Itgs, *, emotion: str
) -> Optional[bytes]:
    """Fetches the serialized instructor category biases for the given emotion from
    redis, if they exist.
    """
    redis = await itgs.redis()
    result = await redis.get(
        f"personalization:instructor_category_biases:{emotion}".encode("utf-8")
    )
    if result is None:
        return None
    assert isinstance(result, bytes), type(result)
    return result


async def set_instructor_category_and_biases_in_redis(
    itgs: Itgs, *, emotion: str, serialized: bytes
) -> None:
    """Writes the serialized instructor category biases for the given emotion to
    redis.
    """
    redis = await itgs.redis()
    await redis.set(
        f"personalization:instructor_category_biases:{emotion}".encode("utf-8"),
        serialized,
        ex=REDIS_CACHE_TIME_SECONDS,
    )


async def get_instructor_category_and_biases_from_db(
    itgs: Itgs, *, emotion: str
) -> List[InstructorCategoryAndBias]:
    """Fetches the instructor, category, bias combinations from the database."""
    conn = await itgs.conn()
    cursor = conn.cursor("none")

    response = await cursor.execute(
        """
        SELECT
            instructors.uid,
            instructors.name,
            instructors.bias,
            journey_subcategories.uid,
            journey_subcategories.internal_name,
            journey_subcategories.bias
        FROM instructors, journey_subcategories
        WHERE
            EXISTS (
                SELECT 1 FROM journeys
                WHERE
                    journeys.instructor_id = instructors.id
                    AND journeys.journey_subcategory_id = journey_subcategories.id
                    AND journeys.deleted_at IS NULL
                    AND journeys.special_category IS NULL
                    AND NOT EXISTS (
                        SELECT 1 FROM course_journeys, courses
                        WHERE 
                            course_journeys.journey_id = journeys.id
                            AND courses.id = course_journeys.course_id
                            AND (courses.flags & ?) = 0
                    )
                    AND EXISTS (
                        SELECT 1 FROM journey_emotions, emotions
                        WHERE
                            journey_emotions.journey_id = journeys.id
                            AND journey_emotions.emotion_id = emotions.id
                            AND emotions.word = ?
                    )
            )
        """,
        (int(SeriesFlags.JOURNEYS_IN_SERIES_ARE_1MINUTE), emotion),
    )

    result: List[InstructorCategoryAndBias] = []
    for row in response.results or []:
        result.append(
            InstructorCategoryAndBias(
                instructor_uid=row[0],
                instructor_name=row[1],
                instructor_bias=row[2],
                category_uid=row[3],
                category_internal_name=row[4],
                category_bias=row[5],
            )
        )
    return result
