import asyncio
import random
import secrets
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Dict, List, Literal, NoReturn, Optional, Tuple, Union
from error_middleware import handle_contextless_error, handle_error
from image_files.models import ImageFileRef
import auth
import interactive_prompts.auth
import image_files.auth
from interactive_prompts.lib.read_interactive_prompt_meta import (
    read_interactive_prompt_meta,
)
from models import (
    StandardErrorResponse,
    STANDARD_ERRORS_BY_CODE,
    AUTHORIZATION_UNKNOWN_TOKEN,
)
import perpetual_pub_sub as pps
from pypika import Query, Table, Parameter, Order
from pypika.queries import QueryBuilder
from pypika.terms import ExistsCriterion
from itgs import Itgs
import time
import io


router = APIRouter()


class ReadInteractivePromptProfilePicturesRequest(BaseModel):
    uid: str = Field(
        description="The UID of the interactive prompt to get a list of profile pictures for"
    )

    jwt: str = Field(
        description="The JWT which allows access to the interactive prompt"
    )

    prompt_time: float = Field(
        description=(
            "The offset relative to the start of the prompt to get "
            "the profile pictures for. May be rounded by the server; "
            "(multiples of) 2 second increments starting at 0 are "
            "recommended."
        ),
        ge=0,
    )

    limit: int = Field(
        description="The maximum number of profile pictures to return", ge=1, le=10
    )


class ReadInteractivePromptProfilePicturesResponseItem(BaseModel):
    picture: ImageFileRef = Field(description="The profile picture for the user")


class ReadInteractivePromptProfilePicturesResponse(BaseModel):
    items: List[ReadInteractivePromptProfilePicturesResponseItem] = Field(
        description="The list of profile pictures"
    )


ERROR_404_TYPES = Literal["interactive_prompt_not_found"]
NOT_FOUND = Response(
    content=(
        StandardErrorResponse[ERROR_404_TYPES](
            type="interactive_prompt_not_found",
            message=(
                "Although you provided valid authentication, there is no interactive prompt "
                "with that UID - it may have been deleted. Alternatively, the prompt "
                "time specified might be outside the range of the prompt."
            ),
        )
        .json()
        .encode("utf-8")
    ),
    status_code=404,
)


@router.post(
    "/profile_pictures",
    response_model=ReadInteractivePromptProfilePicturesResponse,
    responses={
        "404": {
            "description": (
                "Although you provided valid authentication, there is no interactive prompt "
                "with that UID - it may have been deleted. Alternatively, the prompt "
                "time specified might be outside the range of the prompt."
            ),
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def read_profile_pictures(
    args: ReadInteractivePromptProfilePicturesRequest,
    authorization: Optional[str] = Header(None),
):
    """Provides a list of profile pictures that would be reasonable to show
    at the given point in the given interactive prompt for the given user. Since this
    may be tailored to the individual, it requires both the JWT providing
    access to the interactive prompt and standard authorization.
    """
    async with Itgs() as itgs:
        std_auth_result = await auth.auth_any(itgs, authorization)
        if not std_auth_result.success:
            return std_auth_result.error_response

        interactive_prompt_auth_result = await interactive_prompts.auth.auth_any(
            itgs, f"bearer {args.jwt}"
        )
        if not interactive_prompt_auth_result.success:
            return interactive_prompt_auth_result.error_response

        if interactive_prompt_auth_result.result.interactive_prompt_uid != args.uid:
            return AUTHORIZATION_UNKNOWN_TOKEN

        interactive_prompt_uid = args.uid
        prompt_time = int(args.prompt_time / 2) * 2
        # Round down to 2 second increment. If we round to nearest, then if they
        # do 3.5 for a 3.7 second prompt, we return 404, which is very
        # confusing for the api consumer

        user_sub = std_auth_result.result.sub

        standard_pictures = await get_standard_profile_pictures(
            itgs, interactive_prompt_uid, prompt_time
        )
        if standard_pictures is None:
            return NOT_FOUND

        customization = await get_customizations(
            itgs, user_sub, interactive_prompt_uid, prompt_time
        )

        internal_refs = customization.forced[: args.limit]
        if len(internal_refs) < args.limit:
            suppressed_set = frozenset(sup.user_sub for sup in customization.suppressed)
            for internal_ref in standard_pictures.profile_pictures:
                if internal_ref.user_sub not in suppressed_set:
                    internal_refs.append(internal_ref)
                    if len(internal_refs) >= args.limit:
                        break

        return Response(
            content=(
                ReadInteractivePromptProfilePicturesResponse(
                    items=[
                        ReadInteractivePromptProfilePicturesResponseItem(
                            picture=ImageFileRef(
                                uid=internal_ref.image_file_uid,
                                jwt=await image_files.auth.create_jwt(
                                    itgs, internal_ref.image_file_uid
                                ),
                            )
                        )
                        for internal_ref in internal_refs
                    ]
                )
                .json()
                .encode("utf-8")
            ),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "private, max-age=120",
            },
        )


class InternalProfilePictureRef(BaseModel):
    """An internal reference to a profile picture, which we store in our caches"""

    user_sub: str = Field(description="The user's sub")
    image_file_uid: str = Field(description="The UID of the image file")


class UserProfilePicturesCustomization(BaseModel):
    """Describes what customization is required for a users profile pictures within
    a particular interactive prompt at a particular time. It's not generally beneficial to cache
    this value since the user only retrieves it once.
    """

    interactive_prompt_uid: str = Field(
        description="The UID of the interactive prompt this customization is for"
    )
    prompt_time: int = Field(description="The prompt time this customization is for")
    fetched_at: float = Field(
        description="When we fetched this customization from the database"
    )
    suppressed: List[InternalProfilePictureRef] = Field(
        description=(
            "The profile pictures that should never be shown from the standard list"
        )
    )
    forced: List[InternalProfilePictureRef] = Field(
        description=(
            "The profile pictures that should be added, in order, before the standard ones."
        )
    )


class StandardUserProfilePictures(BaseModel):
    """A list of profile pictures to return for a particular interactive prompt at a particular
    time. Prior to customization, it is generally beneficial to cache this value.
    """

    interactive_prompt_uid: str = Field(
        description="The UID of the interactive prompt these pictures are for"
    )
    prompt_time: int = Field(description="The prompt time these pictures are for")
    fetched_at: float = Field(description="When we fetched this list from the database")
    profile_pictures: List[InternalProfilePictureRef] = Field(
        description="The list of profile pictures to return, usually at least 25 to account for suppressed pictures"
    )


async def get_customizations(
    itgs: Itgs, user_sub: str, interactive_prompt_uid: str, prompt_time: int
) -> UserProfilePicturesCustomization:
    """Fetches the required customizations for the user with the given sub within the
    interactive prompt with the given uid at the given time.

    Args:
        itgs (Itgs): The integrations to (re)use
        user_sub (str): The sub of the user to get customizations for
        interactive_prompt_uid (str): The UID of the interactive prompt to get customizations for
        prompt_time (int): The time within the interactive prompt to get customizations for
    """
    # once implemented, this is primarily intended to return any users the user
    # has reported within the suppressed, and anyone the user has invited which
    # are in interactive prompt at that time within the forced

    return UserProfilePicturesCustomization(
        interactive_prompt_uid=interactive_prompt_uid,
        prompt_time=prompt_time,
        fetched_at=time.time(),
        suppressed=[],
        forced=[],
    )


async def get_standard_profile_pictures(
    itgs: Itgs, interactive_prompt_uid: str, prompt_time: int
) -> Optional[StandardUserProfilePictures]:
    """Fetches the standard profile pictures to show for the given interactive
    prompt at the given time. There are generally more of these then we would
    ever return to make it highly unlikely that suppressed pictures would cause
    too few to be returned.

    Through collaborative caching, this can usually be accomplished without any networking
    calls, though this does deserialize as it will need to be logically merged with the
    users customization. For this to work best it's recommended the prompt time be an
    integer multiple of 2 seconds.

    This uses the following keys to produce a multi-layer, collaborative cache:

    - DISKCACHE: `interactive_prompts:profile_pictures:{uid}:{prompt_time}` layer 1 (local)
    - REDIS: `interactive_prompts:profile_pictures:{uid}:{prompt_time}` layer 2 (regional)
    - REDIS: `interactive_prompts:profile_pictures:cache_lock:{uid}:{prompt_time}` prevents multiple
      instances filling regional cache at the same time
    - REDIS: `ps:interactive_prompts:profile_pictures:push_cache` ensures filling one instance
      cache fills all the instance caches, and allows purging local caches

    Args:
        itgs (Itgs): The integrations to (re)use
        interactive_prompt_uid (str): The UID of the interactive prompt to get profile pictures for
        prompt_time (int): The time within the prompt to get profile pictures for

    Returns:
        StandardUserProfilePictures, None: If the interactive prompt exists and the time is
            before the end of the prompt, the standard profile pictures for that
            prompt at that time are returned. Otherwise None is returned. The
            result is semi-random but somewhat stable due to caching.
    """
    res = await get_standard_profile_pictures_from_local_cache(
        itgs, interactive_prompt_uid, prompt_time
    )
    if res is not None:
        return res

    res = await get_standard_profile_pictures_from_redis(
        itgs, interactive_prompt_uid, prompt_time
    )
    if res is not None:
        await set_standard_profile_pictures_to_local_cache(
            itgs,
            interactive_prompt_uid,
            prompt_time,
            encoded_pictures=res.json().encode("utf-8"),
        )
        return res

    # check if this is even a reasonable question
    prompt_meta = await read_interactive_prompt_meta(
        itgs, interactive_prompt_uid=interactive_prompt_uid
    )
    if prompt_meta is None:
        return None

    if prompt_time > prompt_meta.duration_seconds:
        return None

    redis = await itgs.redis()
    got_lock = await redis.set(
        f"interactive_prompts:profile_pictures:cache_lock:{interactive_prompt_uid}:{prompt_time}".encode(
            "ascii"
        ),
        1,
        nx=True,
        ex=3,
    )
    if not got_lock:
        got_data_event = asyncio.Event()
        got_data_task = asyncio.create_task(got_data_event.wait())

        arr = waiting_for_cache.get((interactive_prompt_uid, prompt_time))
        if arr is None:
            arr = []
            waiting_for_cache[(interactive_prompt_uid, prompt_time)] = arr

        arr.append(got_data_event)

        try:
            await asyncio.wait_for(got_data_task, timeout=3)
            new_data = await get_standard_profile_pictures_from_local_cache(
                itgs, interactive_prompt_uid, prompt_time
            )
            if new_data is not None:
                return new_data

            await handle_contextless_error(
                extra_info="Failed to get data from local cache after notified it was stored there",
            )
            # fall down to as if we got lock
        except asyncio.TimeoutError as e:
            got_data_task.cancel()
            await handle_error(
                e,
                extra_info=(
                    "Timeout waiting for standard profile pictures to be filled in, "
                    "either instance died (this should recover), or it's taking a long "
                    "time (check db health)"
                ),
            )
            try:
                arr.remove(got_data_event)
            except ValueError as e:
                # this shouldn't happen afaik
                await handle_error(
                    e, extra_info="Failed to remove event from waiting list"
                )

            if (
                not arr
                and waiting_for_cache.get((interactive_prompt_uid, prompt_time)) is arr
            ):
                waiting_for_cache.pop((interactive_prompt_uid, prompt_time), None)

            # fall down to as if we got the lock

    new_data = await get_standard_profile_pictures_from_database(
        itgs, interactive_prompt_uid, prompt_time
    )
    new_data_encoded = new_data.json().encode("utf-8")
    await set_standard_profile_pictures_to_redis(
        itgs, interactive_prompt_uid, prompt_time, encoded_pictures=new_data_encoded
    )
    await push_standard_profile_pictures_to_local_caches(
        itgs,
        interactive_prompt_uid,
        prompt_time,
        fetched_at=new_data.fetched_at,
        encoded_pictures=new_data_encoded,
    )
    await redis.delete(
        f"interactive_prompts:profile_pictures:cache_lock:{interactive_prompt_uid}:{prompt_time}".encode(
            "ascii"
        )
    )
    return new_data


async def get_standard_profile_pictures_from_local_cache(
    itgs: Itgs, interactive_prompt_uid: str, prompt_time: int
) -> Optional[StandardUserProfilePictures]:
    """Fetches the standard profile pictures stored in our local cache for the given
    interactive prompt at the given time, if any.

    Args:
        itgs (Itgs): The integrations to (re)use
        interactive_prompt_uid (str): The UID of the interactive prompt to get profile pictures for
        prompt_time (int): The time within the prompt to get profile pictures for

    Returns:
        StandardUserProfilePictures, None: The pictures, or None if not found in the
            local cache
    """
    local_cache = await itgs.local_cache()
    raw = local_cache.get(
        f"interactive_prompts:profile_pictures:{interactive_prompt_uid}:{prompt_time}".encode(
            "ascii"
        )
    )
    if raw is None:
        return None
    return StandardUserProfilePictures.parse_raw(raw, content_type="application/json")


async def set_standard_profile_pictures_to_local_cache(
    itgs: Itgs,
    interactive_prompt_uid: str,
    prompt_time: int,
    *,
    encoded_pictures: bytes,
    expire: int = 120,
) -> None:
    """Inserts or updates the standard profile pictures stored in our local cache for
    the given prompt at the given time, expiring after the given number of seconds.
    This tags the cache entry with 'collab', ensuring it's evicted if the instance
    restarts, regardless of the expiration time.

    Args:
        itgs (Itgs): The integrations to (re)use
        interactive_prompt_uid (str): The UID of the prompt to set the profile pictures of
        prompt_time (int): The time within the prompt to set the profile pictures of
        encoded_pictures (bytes): The pictures to set, encoded already
        expire (int): The number of seconds to expire the cache entry after
    """
    local_cache = await itgs.local_cache()
    local_cache.set(
        f"interactive_prompts:profile_pictures:{interactive_prompt_uid}:{prompt_time}".encode(
            "ascii"
        ),
        encoded_pictures,
        expire=expire,
        tag="collab",
    )


async def delete_standard_profile_pictures_from_local_cache(
    itgs: Itgs, interactive_prompt_uid: str, prompt_time: int
) -> None:
    """Deletes the standard profile pictures stored in our local cache for the given
    interactive prompt at the given time, if any.

    Args:
        itgs (Itgs): The integrations to (re)use
        interactive_prompt_uid (str): The UID of the interactive prompt to delete the profile pictures of
        prompt_time (int): The time within the interactive prompt to delete the profile pictures of
    """
    local_cache = await itgs.local_cache()
    local_cache.delete(
        f"interactive_prompts:profile_pictures:{interactive_prompt_uid}:{prompt_time}".encode(
            "ascii"
        )
    )


async def get_standard_profile_pictures_from_redis(
    itgs: Itgs, interactive_prompt_uid: str, prompt_time: int
) -> Optional[StandardUserProfilePictures]:
    """Gets the standard profile pictures stored in redis for the given prompt at the
    given time, if any.

    Args:
        itgs (Itgs): The integrations to (re)use
        interactive_prompt_uid (str): The UID of the prompt to get profile pictures for
        prompt_time (int): The time within the prompt to get profile pictures for
    """
    redis = await itgs.redis()
    pictures = await redis.get(
        f"interactive_prompts:profile_pictures:{interactive_prompt_uid}:{prompt_time}".encode(
            "ascii"
        )
    )
    if pictures is None:
        return None
    return StandardUserProfilePictures.parse_raw(
        pictures, content_type="application/json"
    )


async def set_standard_profile_pictures_to_redis(
    itgs: Itgs,
    interactive_prompt_uid: str,
    prompt_time: int,
    *,
    encoded_pictures: bytes,
    expire: int = 120,
) -> None:
    """Inserts or updates the standard profile pictures for the given prompt uid at
    the given time into the redis cache.

    Args:
        itgs (Itgs): The integrations to (re)use
        interactive_prompt_uid (str): The UID of the interactive prompt to get profile pictures for
        prompt_time (int): The time within the prompt to get profile pictures for
        encoded_pictures (bytes): The pictures to cache, encoded already
        expire (int): How long to cache the pictures for, in seconds. Defaults to 120.
    """
    redis = await itgs.redis()
    await redis.set(
        f"interactive_prompts:profile_pictures:{interactive_prompt_uid}:{prompt_time}".encode(
            "ascii"
        ),
        encoded_pictures,
        ex=expire,
    )


async def delete_standard_profile_pictures_from_redis(
    itgs: Itgs, interactive_prompt_uid: str, prompt_time: int
) -> None:
    """Deletes the standard profile pictures for the given prompt uid at the given
    time from the redis cache. This should not typically be called directly - for
    eviction, such as because a profile picture was found to be against our TOS, use
    evict_standard_profile_pictures which hits all the caches much more efficiently.

    Arguments:
        itgs (Itgs): The integrations to (re)use
        interactive_prompt_uid (str): The UID of the prompt to get profile pictures for
        prompt_time (int): The time within the prompt to get profile pictures for
    """
    redis = await itgs.redis()
    await redis.delete(
        f"interactive_prompts:profile_pictures:{interactive_prompt_uid}:{prompt_time}".encode(
            "ascii"
        )
    )


async def get_standard_profile_pictures_from_database(
    itgs: Itgs, interactive_prompt_uid: str, prompt_time: int
) -> StandardUserProfilePictures:
    """Finds standard profile pictures for the given interactive prompt uid at the given
    time, using the database. This isn't truly random for performance reasons,
    but tends to appear random enough.

    Args:
        itgs (Itgs): The integrations to (re)use
        interactive_prompt_uid (str): The UID of the prompt to get profile pictures for
        prompt_time (int): The time within the prompt to get profile pictures for

    Returns:
        StandardUserProfilePictures: The standard profile pictures to use for that
            offset within the interactive prompt. If the prompt does not exist, this returns
            an empty list. If the prompt exists but the time is illogical, the
            result will be nonsense.
    """
    conn = await itgs.conn()
    cursor = conn.cursor("none")

    # the trick we want to use is take a column with a uniformly random value in
    # a known range and then take a random number starting at a random offset in
    # that range. This is generally an O(Nlog(M)) operation, where N is the
    # number of rows we are plucking and M is the size of the table. Contrast
    # this to an augment-with-random-and-sort, which is O(Mlog(M)) (much worse).
    # Our actual performance will differ based on the work we have to do on each
    # row, e.g., something like O(Nlog(M)(log(K))^2log(O)(log(P))^2) where K is
    # the number of prompt sessions, O is the number of prompt events, and P
    # is the number of users should be an upper bound. This makes the difference
    # between an N vs M linear factor very dramatic.

    # we can't use user sub since we don't want to guarrantee they are random.
    # we can't use user revenue_cat_id since a client who knows we're
    # doing this can use it to deduce ids given enough samples, and
    # revenue_cat_id is treated as a secret

    # so we instead select from the image_files table, which is a little strange,
    # but those uids are generated by us (random enough) and aren't treated as secrets
    # (so leaking which ones are nearby isn't a problem).

    uid_offset = f"oseh_if_{secrets.token_urlsafe(16)}"
    sort_dir = random.choice(["ASC", "DESC"])
    limit = 25
    query_str, qargs = _make_query(
        interactive_prompt_uid, prompt_time, uid_offset, sort_dir, limit
    )
    fetched_at = time.time()
    response = await cursor.execute(query_str, qargs)

    if response.results is None or len(response.results) < limit:
        # retry, removing the offset
        query_str, qargs = _make_query(
            interactive_prompt_uid, prompt_time, None, None, limit
        )
        fetched_at = time.time()
        response = await cursor.execute(query_str, qargs)

    profile_picture_refs = [
        InternalProfilePictureRef(
            user_sub=user_sub,
            image_file_uid=image_file_uid,
        )
        for (user_sub, image_file_uid) in (response.results or [])
    ]
    random.shuffle(profile_picture_refs)

    return StandardUserProfilePictures(
        interactive_prompt_uid=interactive_prompt_uid,
        prompt_time=prompt_time,
        fetched_at=fetched_at,
        profile_pictures=profile_picture_refs,
    )


def _make_query(
    interactive_prompt_uid: str,
    prompt_time: int,
    uid_offset: Optional[str],
    sort_dir: Optional[Literal["ASC", "DESC"]],
    limit: int,
) -> Tuple[str, list]:
    users = Table("users")
    image_files = Table("image_files")
    interactive_prompt_sessions = Table("interactive_prompt_sessions")
    interactive_prompts = Table("interactive_prompts")
    interactive_prompt_events = Table("interactive_prompt_events")

    query: QueryBuilder = (
        Query.from_(image_files)
        .select(users.sub, image_files.uid)
        .join(users)
        .on(users.picture_image_file_id == image_files.id)
        .where(
            ExistsCriterion(
                Query.from_(interactive_prompt_sessions)
                .select(1)
                .where(interactive_prompt_sessions.user_id == users.id)
                .where(
                    ExistsCriterion(
                        Query.from_(interactive_prompts)
                        .select(1)
                        .where(
                            interactive_prompts.id
                            == interactive_prompt_sessions.interactive_prompt_id
                        )
                        .where(interactive_prompts.uid == Parameter("?"))
                    )
                )
                .where(
                    ExistsCriterion(
                        Query.from_(interactive_prompt_events)
                        .select(1)
                        .where(
                            interactive_prompt_events.interactive_prompt_session_id
                            == interactive_prompt_sessions.id
                        )
                        .where(interactive_prompt_events.evtype == Parameter("?"))
                        .where(interactive_prompt_events.prompt_time <= Parameter("?"))
                    )
                )
                .where(
                    ~ExistsCriterion(
                        Query.from_(interactive_prompt_events)
                        .select(1)
                        .where(
                            interactive_prompt_events.interactive_prompt_session_id
                            == interactive_prompt_sessions.id
                        )
                        .where(interactive_prompt_events.evtype == Parameter("?"))
                        .where(interactive_prompt_events.prompt_time <= Parameter("?"))
                    )
                )
            )
        )
    )
    qargs = [
        interactive_prompt_uid,
        "join",
        prompt_time,
        "leave",
        prompt_time,
    ]

    if uid_offset is not None and sort_dir is not None:
        query = query.where(
            image_files.uid > Parameter("?")
            if sort_dir == "ASC"
            else image_files.uid < Parameter("?")
        ).orderby(image_files.uid, order=Order.asc if sort_dir == "ASC" else Order.desc)
        qargs.append(uid_offset)

    query = query.limit(Parameter("?"))
    qargs.append(limit)

    return query.get_sql(), qargs


async def evict_standard_profile_pictures(
    itgs: Itgs,
    interactive_prompt_uid: str,
    prompt_times: Optional[Union[int, List[int]]] = None,
) -> None:
    """Evicts the standard profile pictures for the given interactive prompt at the
    given time, or if no time is given, all times. All times eviction is done by
    querying the database for the length of the prompt, and then evicting all
    integer times. A slower SCAN/KEYS approach can be used if non-integer times
    were accidentally cached. If the interactive prompt is not found, this falls
    back to KEYS, raising ValueError on non-integer timed keys.

    Args:
        itgs (Itgs): The integrations to (re)use
        interactive_prompt_uid (str): The UID of the interactive prompt to evict profile pictures for
        prompt_times (int, List[int], None): If specified, evicts only the given time(s), otherwise
            evicts all times
    """
    redis = await itgs.redis()
    if prompt_times is None:
        meta = await read_interactive_prompt_meta(
            itgs, interactive_prompt_uid=interactive_prompt_uid
        )
        if meta is not None:
            return await evict_standard_profile_pictures(
                itgs,
                interactive_prompt_uid,
                list(range(0, int(meta.duration_seconds + 1))),
            )

        matching_keys = await redis.keys(
            f"interactive_prompts:profile_pictures:{interactive_prompt_uid}:*".encode(
                "ascii"
            )
        )
        matching_keys = [
            str(key, "ascii") if not isinstance(key, str) else key
            for key in matching_keys
        ]
        matching_times = [int(key.split(":")[-1]) for key in matching_keys]
        return await evict_standard_profile_pictures(
            itgs, interactive_prompt_uid, matching_times
        )

    if isinstance(prompt_times, int):
        prompt_times = [prompt_times]
    if not prompt_times:
        return

    now = time.time()
    async with redis.pipeline() as pipe:
        pipe.multi()
        await pipe.delete(
            *[
                f"interactive_prompts:profile_pictures:{interactive_prompt_uid}:{prompt_time}".encode(
                    "ascii"
                )
                for prompt_time in prompt_times
            ]
        )
        for prompt_time in prompt_times:
            msg_body = InteractivePromptProfilePicturesPushCachePubSubMessage(
                uid=interactive_prompt_uid,
                prompt_time=prompt_time,
                min_checked_at=now,
                have_updated=False,
            )
            msg = len(msg_body).to_bytes(
                4, "big", signed=False
            ) + msg_body.json().encode("utf-8")
            await pipe.publish(
                b"ps:interactive_prompts:profile_pictures:push_cache", msg
            )
        await pipe.execute()


async def push_standard_profile_pictures_to_local_caches(
    itgs: Itgs,
    interactive_prompt_uid: str,
    prompt_time: float,
    *,
    fetched_at: float,
    encoded_pictures: bytes,
) -> None:
    """Pushes the given encoded pictures to the local cache for all instances, including
    our own. This does not write to the redis cache.

    Args:
        itgs (Itgs): The integrations to (re)use
        interactive_prompt_uid (str): The UID of the interactive prompt
        prompt_time (float): The time within the interactive prompt
        fetched_at (float): The time at which the pictures were fetched
        encoded_pictures (bytes): The pictures, already json-encoded
    """
    first_part = (
        InteractivePromptProfilePicturesPushCachePubSubMessage(
            uid=interactive_prompt_uid,
            prompt_time=prompt_time,
            min_checked_at=fetched_at,
            have_updated=True,
        )
        .json()
        .encode("utf-8")
    )

    message = io.BytesIO(bytearray(4 + len(first_part) + len(encoded_pictures)))
    message.write(len(first_part).to_bytes(4, "big", signed=False))
    message.write(first_part)
    message.write(encoded_pictures)

    message = message.getvalue()

    redis = await itgs.redis()
    await redis.publish(b"ps:interactive_prompts:profile_pictures:push_cache", message)


class InteractivePromptProfilePicturesPushCachePubSubMessage(BaseModel):
    uid: str = Field(description="The UID of the interactive prompt")
    prompt_time: int = Field(description="The time within the prompt")
    min_checked_at: float = Field(
        description="The minimum checked at time; caches older should be purged"
    )
    have_updated: bool = Field(
        description="If this is followed by the new StandardUserProfilePictures"
    )


waiting_for_cache: Dict[Tuple[str, int], List[asyncio.Event]] = dict()
"""A mutable dictionary mapping from (uid, prompt_time) to the list of asyncio
events to set if we receive new standard user profile pictures for that prompt.
The list is removed before the events are set, so the events are only set once.
However, the push cache loop never cleans this if it doesn't receive a relevant
message, so callee's should set a timeout and clean up if they don't receive
a response in time.
"""


async def cache_push_loop() -> NoReturn:
    """Loops until the perpetual pub sub shuts down, handling any messages from other
    instances regarding standard profile pictures that have been updated and writing
    them to our internal cache.
    """
    try:
        async with pps.PPSSubscription(
            pps.instance,
            "ps:interactive_prompts:profile_pictures:push_cache",
            "ip_pp_pcl",
        ) as sub:
            async for raw_message_bytes in sub:
                raw_message = io.BytesIO(raw_message_bytes)
                first_part_len = int.from_bytes(
                    raw_message.read(4), "big", signed=False
                )
                first_part = (
                    InteractivePromptProfilePicturesPushCachePubSubMessage.parse_raw(
                        raw_message.read(first_part_len),
                        content_type="application/json",
                    )
                )

                if first_part.have_updated:
                    updated_part = raw_message.read()

                async with Itgs() as itgs:
                    if not first_part.have_updated:
                        await delete_standard_profile_pictures_from_local_cache(
                            itgs, first_part.uid, first_part.prompt_time
                        )
                        continue

                    await set_standard_profile_pictures_to_local_cache(
                        itgs,
                        first_part.uid,
                        first_part.prompt_time,
                        encoded_pictures=updated_part,
                    )

                    events = waiting_for_cache.pop(
                        (first_part.uid, first_part.prompt_time), []
                    )
                    for event in events:
                        event.set()
    except Exception as e:
        if pps.instance.exit_event.is_set() and isinstance(e, pps.PPSShutdownException):
            return
        await handle_error(e)
    finally:
        print("profile_pictures cache push loop exiting")
