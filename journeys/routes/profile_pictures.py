import asyncio
import random
import secrets
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Dict, List, Literal, NoReturn, Optional, Tuple, Union
from error_middleware import handle_error
from image_files.models import ImageFileRef
import auth
import journeys.auth
import image_files.auth
from models import (
    StandardErrorResponse,
    STANDARD_ERRORS_BY_CODE,
    AUTHORIZATION_UNKNOWN_TOKEN,
)
import perpetual_pub_sub as pps
from journeys.events.helper import get_journey_meta
from pypika import Query, Table, Parameter, Order
from pypika.queries import QueryBuilder
from pypika.terms import ExistsCriterion
from itgs import Itgs
import time
import io


router = APIRouter()


class ReadJourneyProfilePicturesRequest(BaseModel):
    uid: str = Field(
        description="The UID of the journey to get a list of profile pictures for"
    )

    jwt: str = Field(description="The JWT which allows access to the journey")

    journey_time: float = Field(
        description=(
            "The offset relative to the start of the journey to get "
            "the profile pictures for. May be rounded by the server; "
            "(multiples of) 2 second increments starting at 0 are "
            "recommended."
        ),
        ge=0,
    )

    limit: int = Field(
        description="The maximum number of profile pictures to return", ge=1, le=10
    )


class ReadJourneyProfilePicturesResponseItem(BaseModel):
    picture: ImageFileRef = Field(description="The profile picture for the user")


class ReadJourneyProfilePicturesResponse(BaseModel):
    items: List[ReadJourneyProfilePicturesResponseItem] = Field(
        description="The list of profile pictures"
    )


ERROR_404_TYPES = Literal["journey_not_found"]
NOT_FOUND = Response(
    content=(
        StandardErrorResponse[ERROR_404_TYPES](
            type="journey_not_found",
            message=(
                "Although you provided valid authentication, there is no journey "
                "with that UID - it may have been deleted. Alternatively, the journey "
                "time specified might be outside the range of the journey."
            ),
        )
        .json()
        .encode("utf-8")
    ),
    status_code=404,
)


@router.post(
    "/profile_pictures",
    response_model=ReadJourneyProfilePicturesResponse,
    responses={
        "404": {
            "description": (
                "Although you provided valid authentication, there is no journey "
                "with that UID - it may have been deleted. Alternatively, the journey "
                "time specified might be outside the range of the journey."
            ),
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def read_profile_pictures(
    args: ReadJourneyProfilePicturesRequest, authorization: Optional[str] = Header(None)
):
    """Provides a list of profile pictures that would be reasonable to show
    at the given point in the given journey for the given user. Since this
    may be tailored to the individual, it requires both the JWT providing
    access to the journey and standard authorization.
    """
    async with Itgs() as itgs:
        std_auth_result = await auth.auth_any(itgs, authorization)
        if not std_auth_result.success:
            return std_auth_result.error_response

        journey_auth_result = await journeys.auth.auth_any(itgs, f"bearer {args.jwt}")
        if not journey_auth_result.success:
            return journey_auth_result.error_response

        if journey_auth_result.result.journey_uid != args.uid:
            return AUTHORIZATION_UNKNOWN_TOKEN

        journey_uid = args.uid
        journey_time = int(args.journey_time / 2) * 2
        # Round down to 2 second increment. If we round to nearest, then if they
        # do 3.5 for a 3.7 second journey, we return 404, which is very
        # confusing for the api consumer

        user_sub = std_auth_result.result.sub

        standard_pictures = await get_standard_profile_pictures(
            itgs, journey_uid, journey_time
        )
        if standard_pictures is None:
            return NOT_FOUND

        customization = await get_customizations(
            itgs, user_sub, journey_uid, journey_time
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
                ReadJourneyProfilePicturesResponse(
                    items=[
                        ReadJourneyProfilePicturesResponseItem(
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
    a particular journey at a particular time. It's not generally beneficial to cache
    this value since the user only retrieves it once.
    """

    journey_uid: str = Field(
        description="The UID of the journey this customization is for"
    )
    journey_time: int = Field(description="The journey time this customization is for")
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
    """A list of profile pictures to return for a particular journey at a particular
    time. Prior to customization, it is generally beneficial to cache this value.
    """

    journey_uid: str = Field(
        description="The UID of the journey these pictures are for"
    )
    journey_time: int = Field(description="The journey time these pictures are for")
    fetched_at: float = Field(description="When we fetched this list from the database")
    profile_pictures: List[InternalProfilePictureRef] = Field(
        description="The list of profile pictures to return, usually at least 25 to account for suppressed pictures"
    )


async def get_customizations(
    itgs: Itgs, user_sub: str, journey_uid: str, journey_time: int
) -> UserProfilePicturesCustomization:
    """Fetches the required customizations for the user with the given sub within the
    journey with the given uid at the given time.

    Args:
        itgs (Itgs): The integrations to (re)use
        user_sub (str): The sub of the user to get customizations for
        journey_uid (str): The UID of the journey to get customizations for
        journey_time (int): The time within the journey to get customizations for
    """

    # once implemented, this is primarily intended to return any users the user
    # has reported within the suppressed, and anyone the user has invited which
    # are in journey at that time within the forced

    return UserProfilePicturesCustomization(
        journey_uid=journey_uid,
        journey_time=journey_time,
        fetched_at=time.time(),
        suppressed=[],
        forced=[],
    )


async def get_standard_profile_pictures(
    itgs: Itgs, journey_uid: str, journey_time: int
) -> Optional[StandardUserProfilePictures]:
    """Fetches the standard profile pictures to show for the given journey at the given
    time. There are generally more of these then we would ever return to make it highly
    unlikely that suppressed pictures would cause too few to be returned.

    Through collaborative caching, this can usually be accomplished without any networking
    calls, though this does deserialize as it will need to be logically merged with the
    users customization. For this to work best it's recommended the journey time be an
    integer multiple of 2 seconds.

    This uses the following keys to produce a multi-layer, collaborative cache:

    - DISKCACHE: `journeys:profile_pictures:{uid}:{journey_time}` layer 1 (local)
    - REDIS: `journeys:profile_pictures:{uid}:{journey_time}` layer 2 (regional)
    - REDIS: `journeys:profile_pictures:cache_lock:{uid}:{journey_time}` prevents multiple
      instances filling regional cache at the same time
    - REDIS: `ps:journeys:profile_pictures:push_cache` ensures filling one instance
      cache fills all the instance caches, and allows purging local caches

    Args:
        itgs (Itgs): The integrations to (re)use
        journey_uid (str): The UID of the journey to get profile pictures for
        journey_time (int): The time within the journey to get profile pictures for

    Returns:
        StandardUserProfilePictures, None: If the journey exists and the time is
            before the end of the journey, the standard profile pictures for that
            journey at that time are returned. Otherwise None is returned. The
            result is semi-random but somewhat stable due to caching.
    """
    res = await get_standard_profile_pictures_from_local_cache(
        itgs, journey_uid, journey_time
    )
    if res is not None:
        return res

    res = await get_standard_profile_pictures_from_redis(
        itgs, journey_uid, journey_time
    )
    if res is not None:
        await set_standard_profile_pictures_to_local_cache(
            itgs, journey_uid, journey_time, encoded_pictures=res.json().encode("utf-8")
        )
        return res

    # check if this is even a reasonable question
    journey_meta = await get_journey_meta(itgs, journey_uid)
    if journey_meta is None:
        return None

    if journey_time > journey_meta.duration_seconds:
        return None

    redis = await itgs.redis()
    got_lock = await redis.set(
        f"journeys:profile_pictures:cache_lock:{journey_uid}:{journey_time}".encode(
            "ascii"
        ),
        1,
        nx=True,
        ex=3,
    )
    if not got_lock:
        got_data_event = asyncio.Event()
        got_data_task = asyncio.create_task(got_data_event.wait())

        arr = waiting_for_cache.get((journey_uid, journey_time))
        if arr is None:
            arr = []
            waiting_for_cache[(journey_uid, journey_time)] = arr

        arr.append(got_data_event)

        try:
            await asyncio.wait_for(got_data_task, timeout=3)
            new_data = await get_standard_profile_pictures_from_local_cache(
                itgs, journey_uid, journey_time
            )
            if new_data is not None:
                return new_data

            try:
                raise Exception("Failed to get data from local cache")
            except Exception as e:
                await handle_error(
                    e,
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

            # fall down to as if we got the lock

    new_data = await get_standard_profile_pictures_from_database(
        itgs, journey_uid, journey_time
    )
    new_data_encoded = new_data.json().encode("utf-8")
    await set_standard_profile_pictures_to_redis(
        itgs, journey_uid, journey_time, encoded_pictures=new_data_encoded
    )
    await push_standard_profile_pictures_to_local_caches(
        itgs,
        journey_uid,
        journey_time,
        fetched_at=new_data.fetched_at,
        encoded_pictures=new_data_encoded,
    )
    await redis.delete(
        f"journeys:profile_pictures:cache_lock:{journey_uid}:{journey_time}".encode(
            "ascii"
        )
    )
    return new_data


async def get_standard_profile_pictures_from_local_cache(
    itgs: Itgs, journey_uid: str, journey_time: int
) -> Optional[StandardUserProfilePictures]:
    """Fetches the standard profile pictures stored in our local cache for the given
    journey at the given time, if any.

    Args:
        itgs (Itgs): The integrations to (re)use
        journey_uid (str): The UID of the journey to get profile pictures for
        journey_time (int): The time within the journey to get profile pictures for

    Returns:
        StandardUserProfilePictures, None: The pictures, or None if not found in the
            local cache
    """
    local_cache = await itgs.local_cache()
    raw = local_cache.get(
        f"journeys:profile_pictures:{journey_uid}:{journey_time}".encode("ascii")
    )
    if raw is None:
        return None
    return StandardUserProfilePictures.parse_raw(raw, content_type="application/json")


async def set_standard_profile_pictures_to_local_cache(
    itgs: Itgs,
    journey_uid: str,
    journey_time: int,
    *,
    encoded_pictures: bytes,
    expire: int = 120,
) -> None:
    """Inserts or updates the standard profile pictures stored in our local cache for
    the given journey at the given time, expiring after the given number of seconds.
    This tags the cache entry with 'collab', ensuring it's evicted if the instance
    restarts, regardless of the expiration time.

    Args:
        itgs (Itgs): The integrations to (re)use
        journey_uid (str): The UID of the journey to set the profile pictures of
        journey_time (int): The time within the journey to set the profile pictures of
        encoded_pictures (bytes): The pictures to set, encoded already
        expire (int): The number of seconds to expire the cache entry after
    """
    local_cache = await itgs.local_cache()
    local_cache.set(
        f"journeys:profile_pictures:{journey_uid}:{journey_time}".encode("ascii"),
        encoded_pictures,
        expire=expire,
        tag="collab",
    )


async def delete_standard_profile_pictures_from_local_cache(
    itgs: Itgs, journey_uid: str, journey_time: int
) -> None:
    """Deletes the standard profile pictures stored in our local cache for the given
    journey at the given time, if any.

    Args:
        itgs (Itgs): The integrations to (re)use
        journey_uid (str): The UID of the journey to delete the profile pictures of
        journey_time (int): The time within the journey to delete the profile pictures of
    """
    local_cache = await itgs.local_cache()
    local_cache.delete(
        f"journeys:profile_pictures:{journey_uid}:{journey_time}".encode("ascii")
    )


async def get_standard_profile_pictures_from_redis(
    itgs: Itgs, journey_uid: str, journey_time: int
) -> Optional[StandardUserProfilePictures]:
    """Gets the standard profile pictures stored in redis for the given journey at the
    given time, if any.

    Args:
        itgs (Itgs): The integrations to (re)use
        journey_uid (str): The UID of the journey to get profile pictures for
        journey_time (int): The time within the journey to get profile pictures for
    """
    redis = await itgs.redis()
    pictures = await redis.get(
        f"journeys:profile_pictures:{journey_uid}:{journey_time}".encode("ascii")
    )
    if pictures is None:
        return None
    return StandardUserProfilePictures.parse_raw(
        pictures, content_type="application/json"
    )


async def set_standard_profile_pictures_to_redis(
    itgs: Itgs,
    journey_uid: str,
    journey_time: int,
    *,
    encoded_pictures: bytes,
    expire: int = 120,
) -> None:
    """Inserts or updates the standard profile pictures for the given journey uid at
    the given time into the redis cache.

    Args:
        itgs (Itgs): The integrations to (re)use
        journey_uid (str): The UID of the journey to get profile pictures for
        journey_time (int): The time within the journey to get profile pictures for
        encoded_pictures (bytes): The pictures to cache, encoded already
        expire (int): How long to cache the pictures for, in seconds. Defaults to 120.
    """
    redis = await itgs.redis()
    await redis.set(
        f"journeys:profile_pictures:{journey_uid}:{journey_time}".encode("ascii"),
        encoded_pictures,
        ex=expire,
    )


async def delete_standard_profile_pictures_from_redis(
    itgs: Itgs, journey_uid: str, journey_time: int
) -> None:
    """Deletes the standard profile pictures for the given journey uid at the given
    time from the redis cache. This should not typically be called directly - for
    eviction, such as because a profile picture was found to be against our TOS, use
    evict_standard_profile_pictures which hits all the caches much more efficiently.

    Arguments:
        itgs (Itgs): The integrations to (re)use
        journey_uid (str): The UID of the journey to get profile pictures for
        journey_time (int): The time within the journey to get profile pictures for
    """
    redis = await itgs.redis()
    await redis.delete(
        f"journeys:profile_pictures:{journey_uid}:{journey_time}".encode("ascii")
    )


async def get_standard_profile_pictures_from_database(
    itgs: Itgs, journey_uid: str, journey_time: int
) -> StandardUserProfilePictures:
    """Finds standard profile pictures for the given journey uid at the given
    time, using the database. This isn't truly random for performance reasons,
    but tends to appear random enough.

    Args:
        itgs (Itgs): The integrations to (re)use
        journey_uid (str): The UID of the journey to get profile pictures for
        journey_time (int): The time within the journey to get profile pictures for

    Returns:
        StandardUserProfilePictures: The standard profile pictures to use for that
            offset within the journey. If the journey does not exist, this returns
            an empty list. If the journey exists but the time is illogical, the
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
    # the number of journey sessions, O is the number of journey events, and P
    # is the number of users should be an upper bound. This makes the difference
    # between an N vs M linear factor very dramatic.

    # we can't use user sub as they aren't random enough when generated by
    # cognito. we can't use user revenue_cat_id since a client who knows we're
    # doing this can use it to deduce ids given enough samples, and
    # revenue_cat_id is treated as a secret

    # so we instead select from the image_files table, which is a little strange,
    # but those uids are generated by us (random enough) and aren't treated as secrets
    # (so leaking which ones are nearby isn't a problem).

    uid_offset = f"oseh_if_{secrets.token_urlsafe(16)}"
    sort_dir = random.choice(["ASC", "DESC"])

    users = Table("users")
    image_files = Table("image_files")
    journey_sessions = Table("journey_sessions")
    journeys = Table("journeys")
    journey_events = Table("journey_events")

    query: QueryBuilder = (
        Query.from_(image_files)
        .select(users.sub, image_files.uid)
        .join(users)
        .on(users.picture_image_file_id == image_files.id)
        .where(
            ExistsCriterion(
                Query.from_(journey_sessions)
                .select(1)
                .where(journey_sessions.user_id == users.id)
                .where(
                    ExistsCriterion(
                        Query.from_(journeys)
                        .select(1)
                        .where(journeys.id == journey_sessions.journey_id)
                        .where(journeys.uid == Parameter("?"))
                    )
                )
                .where(
                    ExistsCriterion(
                        Query.from_(journey_events)
                        .select(1)
                        .where(journey_events.journey_session_id == journey_sessions.id)
                        .where(journey_events.evtype == Parameter("?"))
                        .where(journey_events.journey_time <= Parameter("?"))
                    )
                )
                .where(
                    ~ExistsCriterion(
                        Query.from_(journey_events)
                        .select(1)
                        .where(journey_events.journey_session_id == journey_sessions.id)
                        .where(journey_events.evtype == Parameter("?"))
                        .where(journey_events.journey_time <= Parameter("?"))
                    )
                )
            )
        )
        .where(
            image_files.uid > Parameter("?")
            if sort_dir == "ASC"
            else image_files.uid < Parameter("?")
        )
        .orderby(image_files.uid, order=Order.asc if sort_dir == "ASC" else Order.desc)
        .limit(Parameter("?"))
    )
    qargs = [
        journey_uid,
        "join",
        journey_time,
        "leave",
        journey_time,
        uid_offset,
        25,
    ]

    query_str = query.get_sql()
    fetched_at = time.time()
    response = await cursor.execute(query_str, qargs)

    profile_picture_refs = [
        InternalProfilePictureRef(
            user_sub=user_sub,
            image_file_uid=image_file_uid,
        )
        for (user_sub, image_file_uid) in response.results
    ]
    random.shuffle(profile_picture_refs)

    return StandardUserProfilePictures(
        journey_uid=journey_uid,
        journey_time=journey_time,
        fetched_at=fetched_at,
        profile_pictures=profile_picture_refs,
    )


async def evict_standard_profile_pictures(
    itgs: Itgs, journey_uid: str, journey_times: Optional[Union[int, List[int]]] = None
) -> None:
    """Evicts the standard profile pictures for the given journey at the given time,
    or if no time is given, all times. All times eviction is done by querying the
    database for the length of the journey, and then evicting all integer times. A
    slower SCAN/KEYS approach can be used if non-integer times were accidentally
    cached. If the journey is not found, this falls back to KEYS, raising ValueError
    on non-integer timed keys.

    Args:
        itgs (Itgs): The integrations to (re)use
        journey_uid (str): The UID of the journey to evict profile pictures for
        journey_time (int, List[int], None): If specified, evicts only the given time(s), otherwise
            evicts all times
    """
    redis = await itgs.redis()
    if journey_times is None:
        meta = await get_journey_meta(itgs, journey_uid)
        if meta is not None:
            return await evict_standard_profile_pictures(
                itgs, journey_uid, list(range(0, int(meta.duration_seconds + 1)))
            )

        matching_keys = await redis.keys(
            f"journeys:profile_pictures:{journey_uid}:*".encode("ascii")
        )
        matching_keys = [
            str(key, "ascii") if not isinstance(key, str) else key
            for key in matching_keys
        ]
        matching_times = [int(key.split(":")[-1]) for key in matching_keys]
        return await evict_standard_profile_pictures(itgs, journey_uid, matching_times)

    if isinstance(journey_times, int):
        journey_times = [journey_times]
    if not journey_times:
        return

    msg_body = JourneyProfilePicturesPushCachePubSubMessage(
        uid=journey_uid,
        journey_time=journey_time,
        min_checked_at=time.time(),
        have_updated=False,
    )
    msg = len(msg_body).to_bytes(4, "big", signed=False) + msg_body.json().encode(
        "utf-8"
    )
    async with redis.pipeline() as pipe:
        pipe.multi()
        await pipe.delete(
            *[
                f"journeys:profile_pictures:{journey_uid}:{journey_time}".encode(
                    "ascii"
                )
                for journey_time in journey_times
            ]
        )
        for journey_time in journey_times:
            await pipe.publish(b"ps:journeys:profile_pictures:push_cache", msg)
        await pipe.execute()


async def push_standard_profile_pictures_to_local_caches(
    itgs: Itgs,
    journey_uid: str,
    journey_time: float,
    *,
    fetched_at: float,
    encoded_pictures: bytes,
) -> None:
    """Pushes the given encoded pictures to the local cache for all instances, including
    our own. This does not write to the redis cache.

    Args:
        itgs (Itgs): The integrations to (re)use
        journey_uid (str): The UID of the journey
        journey_time (float): The time within the journey
        fetched_at (float): The time at which the pictures were fetched
        encoded_pictures (bytes): The pictures, already json-encoded
    """
    first_part = (
        JourneyProfilePicturesPushCachePubSubMessage(
            uid=journey_uid,
            journey_time=journey_time,
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
    await redis.publish(b"ps:journeys:profile_pictures:push_cache", message)


class JourneyProfilePicturesPushCachePubSubMessage(BaseModel):
    uid: str = Field(description="The UID of the journey")
    journey_time: int = Field(description="The time within the journey")
    min_checked_at: float = Field(
        description="The minimum checked at time; caches older should be purged"
    )
    have_updated: bool = Field(
        description="If this is followed by the new StandardUserProfilePictures"
    )


waiting_for_cache: Dict[Tuple[str, int], List[asyncio.Event]] = dict()
"""A mutable dictionary mapping from (uid, journey_time) to the list of asyncio
events to set if we receive new standard user profile pictures for that journey.
The list is removed before the events are set, so the events are only set once.
However, the push cache loop never cleans this if it doesn't receive a relevant
message, so callee's should set a timeout and clean up if they don't receive
a response in time.
"""


async def push_cache_loop() -> NoReturn:
    """Loops until the perpetual pub sub shuts down, handling any messages from other
    instances regarding standard profile pictures that have been updated and writing
    them to our internal cache.
    """
    async with pps.PPSSubscription(
        pps.instance, "ps:journeys:profile_pictures:push_cache", "jpp_pcl"
    ) as sub:
        async for raw_message_bytes in sub:
            raw_message = io.BytesIO(raw_message_bytes)
            first_part_len = int.from_bytes(raw_message.read(4), "big", signed=False)
            first_part = JourneyProfilePicturesPushCachePubSubMessage.parse_raw(
                raw_message.read(first_part_len), content_type="application/json"
            )

            if first_part.have_updated:
                updated_part = raw_message.read()

            async with Itgs() as itgs:
                if not first_part.have_updated:
                    await delete_standard_profile_pictures_from_local_cache(
                        itgs, first_part.uid, first_part.journey_time
                    )
                    continue

                await set_standard_profile_pictures_to_local_cache(
                    itgs,
                    first_part.uid,
                    first_part.journey_time,
                    encoded_pictures=updated_part,
                )

                events = waiting_for_cache.pop(
                    (first_part.uid, first_part.journey_time), []
                )
                for event in events:
                    event.set()
