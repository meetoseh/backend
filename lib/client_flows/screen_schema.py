"""Provides custom functionality surrounding client_screen schema, which has extension
properties and a format option which we also use for determining how to convert incoming
parameters before realization
"""

from functools import partial
import json
from typing import Any, Callable, List, Optional, Set, Tuple, cast
from error_middleware import handle_warning
import image_files.auth
import content_files.auth
from response_utils import response_to_bytes
import transcripts.auth
import journeys.auth
from image_files.routes.playlist import PlaylistResponse
from itgs import Itgs
import journeys.lib.read_one_external
from courses.lib.get_external_course_from_row import (
    ExternalCourseRow,
    create_standard_external_course_query,
    get_external_course_from_row,
)


UNSAFE_SCREEN_SCHEMA_TYPES: Set[Tuple[str, str]] = {
    ("string", "image_uid"),
    ("string", "content_uid"),
    ("string", "journey_uid"),
    ("string", "course_uid"),
}
KNOWN_COPY_STRING_FORMATS: Set[str] = {
    "date",
    "date-time",
    "password",
    "duration",
    "time",
    "email",
    "idn-email",
    "hostname",
    "idn-hostname",
    "ipv4",
    "ipv6",
    "uri",
    "uri-reference",
    "iri",
    "iri-reference",
    "uuid",
    "uri-template",
    "regex",
    "flow_slug",
}


class ScreenSchemaRealizer:
    def __init__(self, raw_schema: dict) -> None:
        self.raw_schema = raw_schema
        """The raw OpenAPI 3.0.3 schema object"""

    def is_safe(self, path: List[str]) -> Optional[bool]:
        """Returns None if there is no parameter at the given path. Otherwise,
        returns True if its a safe format for untrusted input (i.e., not one of the
        extension formats) and False if it is not safe (e.g., it uses it within a
        JWT claim)
        """
        assert path, "Path must not be empty"

        stack = list(path)
        schema = self.raw_schema

        while True:
            if schema.get("type") != "object":
                return None
            properties = schema.get("properties")
            if properties is None or not isinstance(properties, dict):
                return None

            key = stack.pop(0)
            schema = properties.get(key)
            if schema is None:
                return None

            if not isinstance(schema, dict):
                return None

            if not stack:
                schema_type = schema.get("type")
                schema_format = schema.get("format")

                return (schema_type, schema_format) not in UNSAFE_SCREEN_SCHEMA_TYPES

    async def convert_validated_to_realized(
        self, itgs: Itgs, for_user_sub: str, input: Any
    ) -> Any:
        """Converts input which has been validated against the schema already and
        for which the appropriate trust level has been determined (i.e., either
        the input is entirely trusted, or all the untrusted parts are safe) to
        the realized screen parameters that should be passed onto the client.

        This is essentially the consumer of the schema, as all the screen input
        does is convert a few fields according to their format.
        """
        result: Any = None

        def set_result(v: Any) -> None:
            nonlocal result
            result = v

        stack: List[Tuple[List[str], Any, dict, Callable[[Any], None]]] = [
            (["$"], input, self.raw_schema, set_result)
        ]
        while stack:
            path, given, schema, setter = stack.pop()

            schema_type = schema.get("type")

            if schema_type == "object":
                fmt = schema.get("format")
                assert fmt is None, f"unknown object format {fmt} @ {path}"

                assert isinstance(given, dict), f"expected dict, got {given} @ {path}"

                val = dict()
                setter(val)

                properties = schema.get("properties")
                if properties is None:
                    continue

                assert isinstance(
                    properties, dict
                ), f"expected dict, got {properties} @ {path} properties"

                for key, sub_schema in properties.items():
                    sub_path = path + [key]
                    sub_given = given.get(key)
                    if sub_given is None:
                        continue

                    stack.append(
                        (sub_path, sub_given, sub_schema, partial(val.__setitem__, key))
                    )
            elif schema_type == "array":
                fmt = schema.get("format")
                assert fmt is None, f"unknown array format {fmt} @ {path}"

                assert isinstance(given, list), f"expected list, got {given} @ {path}"

                val = [None] * len(given)
                setter(val)

                items = schema.get("items")
                if items is None:
                    continue

                assert isinstance(
                    items, dict
                ), f"expected dict, got {items} @ {path} items"

                for i, sub_given in enumerate(given):
                    sub_path = path + [str(i)]
                    stack.append(
                        (sub_path, sub_given, items, partial(val.__setitem__, i))
                    )
            elif schema_type == "string":
                fmt = schema.get("format")

                if fmt == "image_uid":
                    assert isinstance(given, str), f"expected str, got {given} @ {path}"
                    x_thumbhash = schema.get("x-thumbhash", {"width": 1, "height": 1})
                    assert isinstance(
                        x_thumbhash, dict
                    ), f"bad x-thumbhash @ {path} for format {fmt}"
                    thumbhash_width = x_thumbhash.get("width")
                    assert isinstance(
                        thumbhash_width, int
                    ), f"bad x-thumbhash @ {path} for format {fmt}"
                    assert (
                        thumbhash_width > 0
                    ), f"bad x-thumbhash @ {path} for format {fmt}"
                    thumbhash_height = x_thumbhash.get("height")
                    assert isinstance(
                        thumbhash_height, int
                    ), f"bad x-thumbhash @ {path} for format {fmt}"
                    assert (
                        thumbhash_height > 0
                    ), f"bad x-thumbhash @ {path} for format {fmt}"

                    setter(
                        await convert_image_uid(
                            itgs, given, thumbhash_width, thumbhash_height
                        )
                    )
                elif fmt == "content_uid":
                    assert isinstance(given, str), f"expected str, got {given} @ {path}"
                    setter(await convert_content_uid(itgs, given))
                elif fmt == "journey_uid":
                    assert isinstance(given, str), f"expected str, got {given} @ {path}"
                    setter(await convert_journey_uid(itgs, given, for_user_sub))
                elif fmt == "course_uid":
                    assert isinstance(given, str), f"expected str, got {given} @ {path}"
                    setter(await convert_course_uid(itgs, given, for_user_sub))
                else:
                    assert (
                        fmt is None or fmt in KNOWN_COPY_STRING_FORMATS
                    ), f"unknown string format {fmt} @ {path}"
                    assert isinstance(given, str), f"expected str, got {given} @ {path}"
                    setter(given)
            elif schema_type == "integer":
                fmt = schema.get("format")
                if fmt == "int32":
                    assert (
                        -(2**31) <= given <= 2**31 - 1
                    ), f"expected int32, got {given} @ {path}"
                elif fmt == "int64":
                    assert (
                        -(2**63) <= given <= 2**63 - 1
                    ), f"expected int64, got {given} @ {path}"
                else:
                    assert fmt is None, f"unknown integer format {fmt} @ {path}"

                assert isinstance(given, int), f"expected int, got {given} @ {path}"
                setter(given)
            elif schema_type == "number":
                fmt = schema.get("format")
                assert fmt in (
                    "float",
                    "double",
                    None,
                ), f"unknown number format {fmt} @ {path}"

                assert isinstance(
                    given, (int, float)
                ), f"expected number, got {given} @ {path}"
                setter(given)
            elif schema_type == "boolean":
                fmt = schema.get("format")
                assert fmt is None, f"unknown boolean format {fmt} @ {path}"

                assert isinstance(given, bool), f"expected bool, got {given} @ {path}"
                setter(given)
            elif schema_type == "null":
                fmt = schema.get("format")
                assert fmt is None, f"unknown null format {fmt} @ {path}"

                assert given is None, f"expected None, got {given} @ {path}"
                setter(None)
            else:
                raise ValueError(f"unknown schema type {schema_type} @ {path}")

        return result


async def convert_image_uid(
    itgs: Itgs, image_uid: str, thumbhash_width: int, thumbhash_height: int
) -> Any:
    """Converts the image UID to the expected format for the client"""
    thumbhash = await try_get_thumbhash_from_dedicated_cache(
        itgs, image_uid, thumbhash_width, thumbhash_height
    )
    if thumbhash is None:
        thumbhash = await try_get_thumbhash_from_playlist_cache(
            itgs, image_uid, thumbhash_width, thumbhash_height
        )
        if thumbhash is not None:
            await set_thumbhash_in_dedicated_cache(
                itgs, image_uid, thumbhash, thumbhash_width, thumbhash_height
            )
    if thumbhash is None:
        thumbhash = await try_get_thumbhash_from_db(
            itgs, image_uid, thumbhash_width, thumbhash_height
        )
        if thumbhash is not None:
            await set_thumbhash_in_dedicated_cache(
                itgs, image_uid, thumbhash, thumbhash_width, thumbhash_height
            )

    return {
        "uid": image_uid,
        "jwt": await image_files.auth.create_jwt(itgs, image_file_uid=image_uid),
        "thumbhash": thumbhash,
    }


async def try_get_thumbhash_from_dedicated_cache(
    itgs: Itgs, image_uid: str, thumbhash_width: int, thumbhash_height: int
) -> Optional[str]:
    result = await _try_get_thumbhash_from_dedicated_local_cache(
        itgs, image_uid, thumbhash_width, thumbhash_height
    )
    if result is not None:
        return result

    result = await _try_get_thumbhash_from_dedicated_redis_cache(
        itgs, image_uid, thumbhash_width, thumbhash_height
    )
    if result is not None:
        await _set_thumbhash_in_dedicated_local_cache(
            itgs, image_uid, result, thumbhash_width, thumbhash_height
        )
    return result


async def set_thumbhash_in_dedicated_cache(
    itgs: Itgs,
    image_uid: str,
    thumbhash: str,
    thumbhash_width: int,
    thumbhash_height: int,
) -> None:
    await _set_thumbhash_in_dedicated_redis_cache(
        itgs, image_uid, thumbhash, thumbhash_width, thumbhash_height
    )
    await _set_thumbhash_in_dedicated_local_cache(
        itgs, image_uid, thumbhash, thumbhash_width, thumbhash_height
    )


async def _try_get_thumbhash_from_dedicated_redis_cache(
    itgs: Itgs, image_uid: str, thumbhash_width: int, thumbhash_height: int
) -> Optional[str]:
    try:
        redis = await itgs.redis()
        res = cast(
            Optional[bytes],
            await redis.get(
                _thumbhash_key(image_uid, thumbhash_width, thumbhash_height)
            ),
        )
        if res is not None:
            return res.decode("utf-8")
        return None
    except Exception as e:
        await handle_warning(
            f"{__name__}:thumbhash_err", "error fetching thumbhash from redis", e
        )


async def _set_thumbhash_in_dedicated_redis_cache(
    itgs: Itgs,
    image_uid: str,
    thumbhash: str,
    thumbhash_width: int,
    thumbhash_height: int,
):
    try:
        redis = await itgs.redis()
        await redis.set(
            _thumbhash_key(image_uid, thumbhash_width, thumbhash_height),
            thumbhash.encode("utf-8"),
            ex=60 * 60 * 8,
        )
    except Exception as e:
        await handle_warning(
            f"{__name__}:thumbhash_err", "error setting thumbhash in redis", e
        )


async def _try_get_thumbhash_from_dedicated_local_cache(
    itgs: Itgs, image_uid: str, thumbhash_width: int, thumbhash_height: int
) -> Optional[str]:
    cache = await itgs.local_cache()
    res = cast(
        Optional[bytes],
        cache.get(_thumbhash_key(image_uid, thumbhash_width, thumbhash_height)),
    )
    if res is not None:
        return res.decode("utf-8")
    return None


async def _set_thumbhash_in_dedicated_local_cache(
    itgs: Itgs,
    image_uid: str,
    thumbhash: str,
    thumbhash_width: int,
    thumbhash_height: int,
):
    cache = await itgs.local_cache()
    # we don't need to collab these since it's not important if its a bit
    # stale: the only thing that might have changed is a new export was added
    # thats a closer match to the requested size, but the thumbhashes will be
    # very similar (if not identical, as is often the case) anyway
    cache.set(
        _thumbhash_key(image_uid, thumbhash_width, thumbhash_height),
        thumbhash.encode("utf-8"),
        expire=60 * 60 * 8,
    )


def _thumbhash_key(image_uid: str, width: int, height: int) -> bytes:
    return f"thumbhashes:{image_uid}:{width}x{height}".encode("utf-8")


async def try_get_thumbhash_from_playlist_cache(
    itgs: Itgs, image_uid: str, thumbhash_width: int, thumbhash_height: int
) -> Optional[str]:
    """Tries to use the locally available playlist cache that is intended primarily
    for image_files.routes.playlist to determine the appropriate thumbhash without
    network calls. This will only work if we've recently served that image without
    presigning, but it's worth checking since we save a ton of time if it's available
    and the only cost is 1 local sqlite query with no results if it's not there

    O(N log N + M) where N is the number of formats and M is the number of exports
    """
    cache = await itgs.local_cache()
    raw_playlist_response = cast(
        Optional[bytes], cache.get(f"image_files:playlist:{image_uid}".encode("utf-8"))
    )
    if raw_playlist_response is None:
        return None

    playlist_response = PlaylistResponse.model_validate_json(raw_playlist_response)

    target_width_over_height = thumbhash_width / thumbhash_height
    target_height_over_width = thumbhash_height / thumbhash_width
    target_size = thumbhash_width * thumbhash_height

    sorted_formats = sorted(playlist_response.items.keys(), reverse=True)

    best: Optional[Tuple[float, int, str, str]] = None
    # min(delta width/height, delta height/width), delta size, uid, thumbhash
    for format in sorted_formats:
        for export in playlist_response.items[format]:
            if export.width <= 0 or export.height <= 0:
                continue

            if export.width == thumbhash_width and export.height == thumbhash_height:
                return export.thumbhash

            aspect_ratio_distance = min(
                abs(export.width / export.height - target_width_over_height),
                abs(export.height / export.width - target_height_over_width),
            )
            if best is not None and aspect_ratio_distance > best[0]:
                continue

            size_distance = abs(export.width * export.height - target_size)
            key = (
                aspect_ratio_distance,
                size_distance,
                export.uid,
                export.thumbhash,
            )
            if best is None or key < best:
                best = key

    return best[3] if best is not None else None


async def try_get_thumbhash_from_db(
    itgs: Itgs, image_uid: str, thumbhash_width: int, thumbhash_height: int
) -> Optional[str]:
    """If there is an image file with the given uid, returns the best thumbhash
    to use for that image given it will be rendered at the given thumbhash width
    and height.

    This requires relatively little communication between us and the database,
    but requires at least O(log(N) * M * log(M)) where N is the number of
    exports in total and M is the number of exports on this image file of work by
    the database

    Args:
        itgs (Itgs): the integrations to (re)use
        image_uid (str): the image file uid
        thumbhash_width (int): the desired width of the export whose thumbhash to use
        thumbhash_height (int): the desired height of the export whose thumbhash to use
    """
    conn = await itgs.conn()
    cursor = conn.cursor("none")

    response = await cursor.execute(
        """
SELECT thumbhash
FROM image_file_exports
WHERE
    image_file_exports.image_file_id = (
        SELECT image_files.id FROM image_files WHERE image_files.uid = ?
    )
ORDER BY
    MIN(ABS(width/height - ?), ABS(height/width - ?)) ASC,
    ABS(width*height - ?) ASC,
    format DESC,
    uid ASC
LIMIT 1
        """,
        (
            image_uid,
            thumbhash_width / thumbhash_height,
            thumbhash_height / thumbhash_width,
            thumbhash_width * thumbhash_height,
        ),
    )
    if not response.results:
        return None

    return response.results[0][0]


async def convert_content_uid(itgs: Itgs, content_uid: str) -> Any:
    """Converts the content UID to the expected format for the client"""
    result = {
        "content": {
            "uid": content_uid,
            "jwt": await content_files.auth.create_jwt(itgs, content_uid),
        },
        "transcript": None,
    }

    transcript_uid = await _get_transcript_uid(itgs, content_uid)
    if transcript_uid is not None:
        result["transcript"] = {
            "uid": transcript_uid,
            "jwt": await transcripts.auth.create_jwt(itgs, transcript_uid),
        }

    return result


async def _get_transcript_uid(itgs: Itgs, content_uid: str) -> Optional[str]:
    """Gets the most recent transcript UID for the given content UID, if any exists"""
    # Unlike image file thumbhashes, i don't currently imagine these being common enough
    # to warrant careful caching, plus transcripts changing meaningfully is allowed
    # so caching would be harder, plus this is a very light query for the database
    # to handle

    conn = await itgs.conn()
    cursor = conn.cursor("none")
    response = await cursor.execute(
        """
SELECT transcripts.uid
FROM content_files, content_file_transcripts, transcripts
WHERE
    content_files.uid = ?
    AND content_files.id = content_file_transcripts.content_file_id
    AND content_file_transcripts.transcript_id = transcripts.id
ORDER BY transcripts.created_at DESC, transcripts.uid ASC
LIMIT 1
        """,
        (content_uid,),
    )
    if not response.results:
        return None
    return response.results[0][0]


async def convert_journey_uid(itgs: Itgs, journey_uid: str, user_sub: str) -> Any:
    """Converts the journey UID to the expected format for the client"""
    response = await journeys.lib.read_one_external.read_one_external(
        itgs,
        journey_uid=journey_uid,
        jwt=await journeys.auth.create_jwt(itgs, journey_uid=journey_uid),
    )

    if response is None:
        return None

    raw = await response_to_bytes(response)
    external_journey = json.loads(raw)

    conn = await itgs.conn()
    cursor = conn.cursor("weak")
    response = await cursor.execute(
        """
SELECT
    (
        SELECT user_journeys.created_at FROM users, journeys, user_journeys
        WHERE
            users.sub = ?
            AND user_journeys.user_id = users.id
            AND journeys.uid = ?
            AND user_journey.journey_id = journeys.id
        ORDER BY user_journeys.created_at DESC
        LIMIT 1
    ) AS last_taken_at,
    (
        SELECT user_likes.created_at FROM users, journeys, user_likes
        WHERE
            users.sub = ?
            AND user_likes.user_id = users.id
            AND journeys.uid = ?
            AND user_likes.journey_id = journeys.id
    ) AS liked_at
        """,
        (user_sub, journey_uid, user_sub, journey_uid),
    )
    assert response.results, response
    last_taken_at = cast(Optional[float], response.results[0][0])
    liked_at = cast(Optional[float], response.results[0][1])

    return {
        "journey": external_journey,
        "last_taken_at": last_taken_at,
        "liked_at": liked_at,
    }


async def convert_course_uid(itgs: Itgs, course_uid: str, user_sub: str) -> Any:
    """Converts the course UID to the expected format for the client"""
    # PERF: Currently I don't _think_ this is going to be used that often, but it
    #   probably could use a cache broken up in the same way the journey cache is
    #   broken into the standard parts and the user part
    conn = await itgs.conn()
    cursor = conn.cursor("none")

    query, qargs = create_standard_external_course_query(user_sub)
    response = await cursor.execute(
        query + " WHERE uid=?",
        qargs + [course_uid],
    )
    if not response.results:
        return None

    parsed = await get_external_course_from_row(
        itgs,
        user_sub=user_sub,
        row=ExternalCourseRow(*response.results[0]),
    )
    return parsed.model_dump()
