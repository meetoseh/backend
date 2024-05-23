"""Provides custom functionality surrounding client_screen schema, which has extension
properties and a format option which we also use for determining how to convert incoming
parameters before realization
"""

from functools import partial
import gzip
import json
from typing import Any, Callable, List, Optional, Set, Tuple, Union, cast
from error_middleware import handle_warning
import image_files.auth
import content_files.auth
from lib.client_flows.helper import pretty_path
from lib.client_flows.special_index import SpecialIndex
from resources.patch.not_set import NotSetEnum
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
from dataclasses import dataclass


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


@dataclass(frozen=True)
class _RealizeState:
    path: List[str]
    given: Any
    schema: dict
    setter: Callable[[Any], None]


class ScreenSchemaRealizer:
    def __init__(self, raw_schema: dict) -> None:
        self.raw_schema = raw_schema
        """The raw OpenAPI 3.0.3 schema object"""

    def is_safe(
        self, path: Union[List[Union[str, SpecialIndex]], List[str], List[SpecialIndex]]
    ) -> Optional[bool]:
        """Returns None if there is no parameter at the given path. Otherwise,
        returns True if its a safe format for untrusted input (i.e., not one of the
        extension formats) and False if it is not safe (e.g., it uses it within a
        JWT claim)
        """
        stack = list(path)
        schema = self.raw_schema

        while stack:
            if schema.get("type") == "array":
                items = schema.get("items")
                if items is None or not isinstance(items, dict):
                    return None
                key = stack.pop(0)
                if key is not SpecialIndex.ARRAY_INDEX:
                    return None
                schema = items
                if not isinstance(schema, dict):
                    return None
                continue

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

        schema_type = schema.get("type")
        schema_format = schema.get("format")

        return (schema_type, schema_format) not in UNSAFE_SCREEN_SCHEMA_TYPES

    def iter_enum_discriminators(self):
        """Yields (path, values) where path is the path to the discriminator and
        values is the set of possible values for that discriminator

        For example, if this schema is

        ```json
        {
            "type": "object",
            "x-enum-discriminator": "type",
            "oneOf": [
                {
                    "type": "object",
                    "required": ["type"],
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["option-a"],
                        }
                    }
                },
                {
                    "type": "object",
                    "required": ["type"],
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["option-b"],
                        }
                    }
                }
            ]
        }
        ```

        this will yield `("type", frozenset(("option-a", "option-b")))`
        """
        stack: List[Tuple[List[Union[str, SpecialIndex]], dict]] = [
            ([], self.raw_schema)
        ]
        while stack:
            path, schema = stack.pop()

            discriminator = schema.get("x-enum-discriminator")
            if discriminator is not None:
                options_set = set()
                options_ordered = list()
                for option in schema.get("oneOf", []):
                    assert isinstance(option, dict), f"bad oneOf @ {path}"
                    properties = option.get("properties", dict())
                    assert isinstance(properties, dict), f"bad properties @ {path}"
                    prop = properties.get(discriminator)
                    assert isinstance(prop, dict), f"bad discriminator @ {path}"
                    enum = prop.get("enum")
                    assert isinstance(enum, list), f"bad enum @ {path} (not a list)"
                    assert len(enum) == 1, f"bad enum @ {path} (too many elements)"
                    option_value = enum[0]
                    assert isinstance(
                        option_value, str
                    ), f"bad value @ {path + ['enum', 0]} (not a string)"
                    assert (
                        option_value not in options_set
                    ), f"duplicate value @ {path + ['enum', 0]}"
                    options_set.add(option_value)
                    options_ordered.append(option_value)

                yield (path + [discriminator], options_ordered)
                # we don't support nesting of discriminators
                continue

            if schema.get("type") == "array":
                items = schema.get("items")
                assert isinstance(items, dict), f"bad items @ {path}"
                stack.append((path + [SpecialIndex.ARRAY_INDEX], items))
                continue

            if schema.get("type") != "object":
                # leaf node
                continue

            properties = schema.get("properties", dict())
            assert isinstance(properties, dict), f"bad properties @ {path}"
            for key, sub_schema in properties.items():
                assert isinstance(sub_schema, dict), f"bad sub_schema @ {path}"
                stack.append((path + [key], sub_schema))

    async def convert_validated_to_realized(
        self, itgs: Itgs, /, *, for_user_sub: str, input: Any
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

        stack: List[_RealizeState] = [
            _RealizeState(
                path=[], given=input, schema=self.raw_schema, setter=set_result
            )
        ]
        while stack:
            state = stack.pop()

            if state.given is NotSetEnum.NOT_SET:
                assert (
                    "default" in state.schema
                ), f"no default @ {pretty_path(state.path)}, despite not set in input"
                stack.append(
                    _RealizeState(
                        path=state.path,
                        given=state.schema["default"],
                        schema=state.schema,
                        setter=state.setter,
                    )
                )
                continue

            schema_type = state.schema.get("type")

            if state.schema.get("nullable", False) is True and state.given is None:
                state.setter(None)
                continue

            if schema_type == "object" and "oneOf" in state.schema:
                discriminator_field = state.schema.get("x-enum-discriminator")
                assert isinstance(
                    discriminator_field, str
                ), f"bad discriminator @ {pretty_path(state.path)}: {discriminator_field=}"
                assert isinstance(
                    state.given, dict
                ), f"expected dict, got {state.given} @ {pretty_path(state.path)}"
                discriminator_value = state.given.get(discriminator_field)
                if discriminator_value is None:
                    top_default = state.schema.get("default")
                    assert isinstance(
                        top_default, dict
                    ), f"bad default @ {pretty_path(state.path)}: {top_default=}"
                    discriminator_value = top_default.get(discriminator_field)
                    assert isinstance(
                        discriminator_value, str
                    ), f"bad default discriminator @ {pretty_path(state.path)}: {discriminator_value=}"
                else:
                    assert isinstance(
                        discriminator_value, str
                    ), f"bad discriminator @ {pretty_path(state.path)}: {discriminator_value=}"

                oneof = state.schema["oneOf"]
                assert isinstance(
                    oneof, list
                ), f"bad oneOf @ {pretty_path(state.path)}: {oneof=}"
                for option in oneof:
                    assert isinstance(
                        option, dict
                    ), f"bad option @ {pretty_path(state.path)}: {option=}"
                    properties = option.get("properties")
                    assert isinstance(
                        properties, dict
                    ), f"bad properties @ {pretty_path(state.path)}: {properties=}"
                    discriminator = properties.get(discriminator_field)
                    assert isinstance(
                        discriminator, dict
                    ), f"bad discriminator @ {pretty_path(state.path)}: {discriminator=}"
                    enum = discriminator.get("enum")
                    assert isinstance(
                        enum, list
                    ), f"bad enum @ {pretty_path(state.path)}: {enum=}"
                    assert (
                        len(enum) == 1
                    ), f"bad enum @ {pretty_path(state.path)}: {enum=}"
                    option_value = enum[0]
                    assert isinstance(
                        option_value, str
                    ), f"bad option value @ {pretty_path(state.path)}: {option_value=}"
                    if option_value == discriminator_value:
                        stack.append(
                            _RealizeState(
                                path=state.path,
                                given=state.given,
                                schema=option,
                                setter=state.setter,
                            )
                        )
                        break
                else:
                    raise ValueError(
                        f"bad discriminator value @ {pretty_path(state.path)}: {discriminator_value=}"
                    )
            elif schema_type == "object":
                fmt = state.schema.get("format")
                assert (
                    fmt is None
                ), f"unknown object format {fmt} @ {pretty_path(state.path)}"
                assert isinstance(
                    state.given, dict
                ), f"expected dict, got {state.given} @ {pretty_path(state.path)}"

                val = dict()
                state.setter(val)

                properties = state.schema.get("properties")
                if properties is None:
                    continue

                assert isinstance(
                    properties, dict
                ), f"expected dict, got {properties} @ {pretty_path(state.path + ['properties'])}"

                for key, sub_schema in properties.items():
                    sub_path = state.path + [key]
                    sub_given = state.given.get(key, NotSetEnum.NOT_SET)
                    stack.append(
                        _RealizeState(
                            path=sub_path,
                            given=sub_given,
                            schema=sub_schema,
                            setter=partial(val.__setitem__, key),
                        )
                    )
            elif schema_type == "array":
                fmt = state.schema.get("format")
                assert (
                    fmt is None
                ), f"unknown array format {fmt} @ {pretty_path(state.path)}"

                assert isinstance(
                    state.given, list
                ), f"expected list, got {state.given} @ {pretty_path(state.path)}"

                val = [None] * len(state.given)
                state.setter(val)

                items = state.schema.get("items")
                if items is None:
                    continue

                assert isinstance(
                    items, dict
                ), f"expected dict, got {items} @ {pretty_path(state.path)} items"

                for i, sub_given in enumerate(state.given):
                    sub_path = state.path + [str(i)]
                    stack.append(
                        _RealizeState(
                            path=sub_path,
                            given=sub_given,
                            schema=items,
                            setter=partial(val.__setitem__, i),
                        )
                    )
            elif schema_type == "string":
                fmt = state.schema.get("format")

                if fmt == "image_uid":
                    assert isinstance(
                        state.given, str
                    ), f"expected str, got {state.given} @ {pretty_path(state.path)}"
                    x_thumbhash = state.schema.get(
                        "x-thumbhash", {"width": 1, "height": 1}
                    )
                    assert isinstance(
                        x_thumbhash, dict
                    ), f"bad x-thumbhash @ {pretty_path(state.path)} for format {fmt}"
                    thumbhash_width = x_thumbhash.get("width")
                    assert isinstance(
                        thumbhash_width, int
                    ), f"bad x-thumbhash @ {pretty_path(state.path)} for format {fmt}"
                    assert (
                        thumbhash_width > 0
                    ), f"bad x-thumbhash @ {pretty_path(state.path)} for format {fmt}"
                    thumbhash_height = x_thumbhash.get("height")
                    assert isinstance(
                        thumbhash_height, int
                    ), f"bad x-thumbhash @ {pretty_path(state.path)} for format {fmt}"
                    assert (
                        thumbhash_height > 0
                    ), f"bad x-thumbhash @ {pretty_path(state.path)} for format {fmt}"

                    state.setter(
                        await convert_image_uid(
                            itgs, state.given, thumbhash_width, thumbhash_height
                        )
                    )
                elif fmt == "content_uid":
                    assert isinstance(
                        state.given, str
                    ), f"expected str, got {state.given} @ {pretty_path(state.path)}"
                    state.setter(await convert_content_uid(itgs, state.given))
                elif fmt == "journey_uid":
                    assert isinstance(
                        state.given, str
                    ), f"expected str, got {state.given} @ {pretty_path(state.path)}"
                    state.setter(
                        await convert_journey_uid(itgs, state.given, for_user_sub)
                    )
                elif fmt == "course_uid":
                    assert isinstance(
                        state.given, str
                    ), f"expected str, got {state.given} @ {pretty_path(state.path)}"
                    state.setter(
                        await convert_course_uid(itgs, state.given, for_user_sub)
                    )
                else:
                    assert (
                        fmt is None or fmt in KNOWN_COPY_STRING_FORMATS
                    ), f"unknown string format {fmt} @ {pretty_path(state.path)}"
                    assert isinstance(
                        state.given, str
                    ), f"expected str, got {state.given} @ {pretty_path(state.path)}"
                    state.setter(state.given)
            elif schema_type == "integer":
                assert isinstance(
                    state.given, int
                ), f"expected int, got {state.given} @ {pretty_path(state.path)}"

                fmt = state.schema.get("format")
                if fmt == "int32":
                    assert (
                        -(2**31) <= state.given <= 2**31 - 1
                    ), f"expected int32, got {state.given} @ {pretty_path(state.path)}"
                elif fmt == "int64":
                    assert (
                        -(2**63) <= state.given <= 2**63 - 1
                    ), f"expected int64, got {state.given} @ {pretty_path(state.path)}"
                else:
                    assert (
                        fmt is None
                    ), f"unknown integer format {fmt} @ {pretty_path(state.path)}"

                state.setter(state.given)
            elif schema_type == "number":
                fmt = state.schema.get("format")
                assert fmt in (
                    "float",
                    "double",
                    None,
                ), f"unknown number format {fmt} @ {pretty_path(state.path)}"

                assert isinstance(
                    state.given, (int, float)
                ), f"expected number, got {state.given} @ {pretty_path(state.path)}"
                state.setter(state.given)
            elif schema_type == "boolean":
                fmt = state.schema.get("format")
                assert (
                    fmt is None
                ), f"unknown boolean format {fmt} @ {pretty_path(state.path)}"

                assert isinstance(
                    state.given, bool
                ), f"expected bool, got {state.given} @ {pretty_path(state.path)}"
                state.setter(state.given)
            elif schema_type == "null":
                fmt = state.schema.get("format")
                assert (
                    fmt is None
                ), f"unknown null format {fmt} @ {pretty_path(state.path)}"

                assert (
                    state.given is None
                ), f"expected None, got {state.given} @ {pretty_path(state.path)}"
                state.setter(None)
            else:
                raise ValueError(
                    f"unknown schema type {schema_type} @ {pretty_path(state.path)}"
                )

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

    playlist_response = PlaylistResponse.model_validate_json(
        gzip.decompress(raw_playlist_response)
    )

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
        query + " WHERE courses.uid=?",
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
