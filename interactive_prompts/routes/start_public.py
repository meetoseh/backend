import secrets
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from error_middleware import handle_contextless_error
from interactive_prompts.models.prompt import Prompt, WordPrompt
from typing import Dict, Literal, Optional, Tuple
from interactive_prompts.lib.read_one_external import read_one_external
from interactive_prompts.models.external_interactive_prompt import (
    ExternalInteractivePrompt,
)
from interactive_prompts.auth import create_jwt as create_interactive_prompt_jwt
from auth import auth_any
from itgs import Itgs
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from dataclasses import dataclass
from contextlib import asynccontextmanager
import time


router = APIRouter()


@dataclass
class PublicInteractivePrompt:
    identifier: str
    """The stable, environment-agnostic identifier for this prompt. Typically
    uses snakecase, e.g., 'onboarding-prompt-feeling'
    """

    version: int
    """A number which should start at 0 and be incremented whenever we reuse
    this identifier with different settings.
    """

    prompt: Prompt
    """The prompt settings to use for each instance of this prompt"""

    duration_seconds: int
    """How long in seconds the prompt lasts, i.e., how long the user has to
    respond during the interactive portion.
    """

    expires_seconds: int
    """How long an individual instance of this prompt can last before it is
    expired. Expiration is always set to an integer unix time, so this is only
    accurate to 1 second.
    """


PUBLIC_INTERACTIVE_PROMPTS: Dict[str, PublicInteractivePrompt] = {
    "onboarding-prompt-feeling": PublicInteractivePrompt(
        identifier="onboarding-prompt-feeling",
        version=0,
        prompt=WordPrompt(
            style="word",
            text="Today, I am here to...",
            options=["Relax", "Destress", "Focus"],
        ),
        duration_seconds=60,
        expires_seconds=60 * 60 * 24 * 7 * 4,
    ),
    "onboarding-prompt-feeling-result": PublicInteractivePrompt(
        identifier="onboarding-prompt-feeling-result",
        version=0,
        prompt=WordPrompt(
            style="word",
            text="How did that class make you feel?",
            options=["Calming", "Chill", "I’m Vibing it "],
        ),
        duration_seconds=60,
        expires_seconds=60 * 60 * 24 * 7 * 4,
    ),
    "notification-time": PublicInteractivePrompt(
        identifier="notification-time",
        version=0,
        prompt=WordPrompt(
            style="word",
            text="When do you want to receive text reminders?",
            options=["Morning", "Afternoon", "Evening"],
        ),
        duration_seconds=60,
        expires_seconds=60 * 60 * 24 * 7 * 4,
    ),
}

PublicInteractivePromptKey = Literal[
    "onboarding-prompt-feeling", "onboarding-prompt-feeling-result", "notification-time"
]


class StartPublicInteractivePromptRequest(BaseModel):
    identifier: PublicInteractivePromptKey = Field(
        description="Which public interactive prompt to start"
    )


ERROR_503_TYPES = Literal["session_failed_to_start", "failed_to_read_prompt"]


@router.post(
    "/start_public",
    response_model=ExternalInteractivePrompt,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def start_public_interactive_prompt(
    args: StartPublicInteractivePromptRequest,
    authorization: Optional[str] = Header(None),
):
    """Starts a public interactive prompt based on its identifier. These are
    interactive prompts which are started at particular times in the user
    experience, outside of the standard interactive prompts associated with
    e.g. journeys.

    For example, a public interactive prompt could be used for an onboarding
    poll, or temporarily made public as part of an announcement.

    Requires standard authorization.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        public_prompt = PUBLIC_INTERACTIVE_PROMPTS[args.identifier]
        uid = await get_current_interactive_prompt_uid(
            itgs, public_prompt=public_prompt
        )
        jwt = await create_interactive_prompt_jwt(itgs, interactive_prompt_uid=uid)

        conn = await itgs.conn()
        cursor = conn.cursor()
        session_uid = f"oseh_ips_{secrets.token_urlsafe(16)}"
        response = await cursor.execute(
            """
            INSERT INTO interactive_prompt_sessions (
                interactive_prompt_id, user_id, uid
            )
            SELECT
                interactive_prompts.id, users.id, ?
            FROM interactive_prompts, users
            WHERE
                users.sub = ?
                AND interactive_prompts.uid = ?
                AND interactive_prompts.deleted_at IS NULL
            """,
            (
                session_uid,
                auth_result.result.sub,
                uid,
            ),
        )
        if response.rows_affected is None or response.rows_affected < 1:
            await handle_contextless_error(
                extra_info=f"interactive prompts start_public failed to start session: {public_prompt.identifier=}, {uid=}"
            )
            return Response(
                status_code=503,
                content=StandardErrorResponse[ERROR_503_TYPES](
                    type="session_failed_to_start",
                    message=(
                        "The session failed to start. This could be because the prompt "
                        "has been modified or deleted. Please try again."
                    ),
                ).json(),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Retry-After": "15",
                },
            )

        result = await read_one_external(
            itgs,
            interactive_prompt_uid=uid,
            interactive_prompt_jwt=jwt,
            interactive_prompt_session_uid=session_uid,
        )

        if result is None:
            await handle_contextless_error(
                extra_info=f"interactive prompts start_public failed to read: {public_prompt.identifier=}, {uid=}"
            )
            return Response(
                status_code=503,
                content=StandardErrorResponse[ERROR_503_TYPES](
                    type="failed_to_read_prompt",
                    message=(
                        "The prompt failed to load. This could be because the prompt "
                        "has been modified or deleted. Please try again."
                    ),
                ).json(),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Retry-After": "15",
                },
            )

        return result


class LockedError(Exception):
    def __init__(self, *, public_prompt: PublicInteractivePrompt):
        super().__init__(f"Failed to acquire lock for {public_prompt.identifier}")
        self.public_prompt = public_prompt


class LocallyCachedPublicInteractivePrompt(BaseModel):
    uid: str = Field(description="The uid of the interactive prompt")
    version: int = Field(description="The version of the public interactive prompt")


async def get_current_interactive_prompt_uid(
    itgs: Itgs, *, public_prompt: PublicInteractivePrompt
) -> str:
    """Fetches the uid for the current interactive prompt with the given uid,
    or creates one if it doesn't exist. This will go through a multilayer
    cache and coordinate with other instances.

    Args:
        itgs (Itgs): The integrations to (re)use
        public_prompt (PublicInteractivePrompt): The public prompt to fetch
            the uid for

    Returns:
        str: The uid of the interactive prompt that currently corresponds to
            the public prompt
    """
    cached = await get_current_interactive_prompt_uid_from_local_cache(
        itgs, public_prompt=public_prompt
    )
    if cached is not None:
        return cached

    shared_cached = await get_current_interactive_prompt_uid_and_expiration_from_redis(
        itgs, public_prompt=public_prompt
    )
    if shared_cached is not None:
        await store_interactive_prompt_in_local_cache(
            itgs,
            public_prompt=public_prompt,
            uid=shared_cached[0],
            expires_at=shared_cached[1],
        )
        return shared_cached[0]

    try:
        async with lock_public_interactive_prompt(itgs, public_prompt=public_prompt):
            shared_cached = (
                await get_current_interactive_prompt_uid_and_expiration_from_redis(
                    itgs, public_prompt=public_prompt
                )
            )
            if shared_cached is not None:
                await store_interactive_prompt_in_local_cache(
                    itgs,
                    public_prompt=public_prompt,
                    uid=shared_cached[0],
                    expires_at=shared_cached[1],
                )
                return shared_cached[0]

            uid = await create_interactive_prompt(itgs, public_prompt=public_prompt)
            expires_at = int(time.time()) + public_prompt.expires_seconds
            await store_interactive_prompt_in_local_cache(
                itgs, public_prompt=public_prompt, uid=uid, expires_at=expires_at
            )
            await store_interactive_prompt_in_redis(
                itgs, public_prompt=public_prompt, uid=uid, expires_at=expires_at
            )
            return uid
    except LockedError:
        shared_cached = (
            await get_current_interactive_prompt_uid_and_expiration_from_redis(
                itgs, public_prompt=public_prompt
            )
        )
        if shared_cached is None:
            raise Exception(
                "Failed to acquire lock, but no cached value was found in redis"
            )

        await store_interactive_prompt_in_local_cache(
            itgs,
            public_prompt=public_prompt,
            uid=shared_cached[0],
            expires_at=shared_cached[1],
        )
        return shared_cached[0]


async def get_current_interactive_prompt_uid_from_local_cache(
    itgs: Itgs, *, public_prompt: PublicInteractivePrompt
) -> Optional[str]:
    """If the uid of the interactive prompt currently used for the
    given public prompt is available in the local cache, returns it,
    otherwise returns None.

    This will check if the version stored differs from the version requested,
    and if so, return None.
    """
    local_cache = await itgs.local_cache()
    raw = local_cache.get(
        f"interactive_prompts:special:{public_prompt.identifier}:info".encode("utf-8")
    )
    if raw is None:
        return None

    info = LocallyCachedPublicInteractivePrompt.parse_raw(
        raw, content_type="application/json"
    )
    if info.version != public_prompt.version:
        return None
    return info.uid


async def get_current_interactive_prompt_uid_and_expiration_from_redis(
    itgs: Itgs, *, public_prompt: PublicInteractivePrompt
) -> Optional[Tuple[str, int]]:
    """If the uid of the interactive prompt currently used for the
    given public prompt is available in redis, returns it, otherwise
    returns None. Note that this includes when the interactive prompt
    will no longer be current, so that if it's stored locally we know
    the expiration time.

    This will check if the version stored differs from the version requested,
    and if so, return None.
    """
    redis = await itgs.redis()
    raw = await redis.hmget(
        f"interactive_prompts:special:{public_prompt.identifier}:info".encode("utf-8"),
        b"uid",
        b"version",
        b"expires_at",
    )

    if raw[0] is None:
        return None
    assert raw[1] is not None, "Version should always be set if uid is set"
    assert raw[2] is not None, "Expires at should always be set if uid is set"

    uid = raw[0].decode("utf-8") if isinstance(raw[0], bytes) else raw[0]
    version = int(raw[1])
    expires_at = int(raw[2])

    if version != public_prompt.version:
        return None

    return uid, expires_at


@asynccontextmanager
async def lock_public_interactive_prompt(
    itgs: Itgs, *, public_prompt: PublicInteractivePrompt
):
    """Acquires a lock for the given public interactive prompt, so that
    no other instances are able to acquire this lock until it is released.
    The lock has a short expiration.

    This is used while creating a new interactive prompt for the public
    prompt, so that we don't have multiple instances creating new prompts
    at the same time.

    Raises:
        LockedError: If the lock could not be acquired
    """
    key = f"interactive_prompts:special:{public_prompt.identifier}:lock".encode("utf-8")

    redis = await itgs.redis()
    acquired = await redis.set(key, b"1", ex=5, nx=True)
    if not acquired:
        raise LockedError(public_prompt=public_prompt)

    try:
        yield
    finally:
        await redis.delete(key)


async def create_interactive_prompt(
    itgs: Itgs, *, public_prompt: PublicInteractivePrompt
) -> str:
    """Creates a new interactive prompt for the given public prompt, and
    returns its uid.
    """
    conn = await itgs.conn()
    cursor = conn.cursor()

    uid = f"oseh_ip_{secrets.token_urlsafe(16)}"
    puid = f"oseh_pip_{secrets.token_urlsafe(16)}"

    result = await cursor.executemany3(
        (
            (
                """
                INSERT INTO interactive_prompts (
                    uid, prompt, duration_seconds, created_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    uid,
                    public_prompt.prompt.json(),
                    public_prompt.duration_seconds,
                    time.time(),
                ),
            ),
            (
                """
                INSERT INTO public_interactive_prompts (
                    uid, interactive_prompt_id, public_identifier, version
                )
                SELECT
                    ?, interactive_prompts.id, ?, ?
                FROM interactive_prompts
                WHERE interactive_prompts.uid = ?
                """,
                (puid, public_prompt.identifier, public_prompt.version, uid),
            ),
        )
    )

    assert result[0].rows_affected is not None and result[0].rows_affected > 0
    assert result[1].rows_affected is not None and result[1].rows_affected > 0
    return uid


async def store_interactive_prompt_in_redis(
    itgs: Itgs, *, public_prompt: PublicInteractivePrompt, uid: str, expires_at: int
) -> None:
    """Stores the uid of the interactive prompt currently used for the
    given public prompt in redis, along with the expiration time, and
    marks the key to be expired at the appropriate time.
    """
    redis = await itgs.redis()

    key = f"interactive_prompts:special:{public_prompt.identifier}:info".encode("utf-8")

    async with redis.pipeline() as pipe:
        pipe.multi()
        await pipe.delete(key)
        await pipe.hmset(
            key,
            mapping={
                b"uid": uid.encode("utf-8"),
                b"version": str(public_prompt.version).encode("utf-8"),
                b"expires_at": str(expires_at).encode("utf-8"),
            },
        )
        await pipe.expireat(key, expires_at)
        await pipe.execute()


async def store_interactive_prompt_in_local_cache(
    itgs: Itgs, *, public_prompt: PublicInteractivePrompt, uid: str, expires_at: int
) -> None:
    """Stores the uid of the interactive prompt currently used for the
    given public prompt in the local cache, and marks it to expire at
    the given time.
    """
    expire_in = int(expires_at - time.time())
    if expire_in <= 5:
        return

    local_cache = await itgs.local_cache()
    local_cache.set(
        f"interactive_prompts:special:{public_prompt.identifier}:info".encode("utf-8"),
        LocallyCachedPublicInteractivePrompt(version=public_prompt.version, uid=uid)
        .json()
        .encode("utf-8"),
        expire=expire_in,
    )
