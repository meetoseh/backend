import json
import random
import secrets
import time
from fastapi import APIRouter, Header
from typing import Optional, Union
from interactive_prompts.models.external_interactive_prompt import (
    ExternalInteractivePrompt,
)
from interactive_prompts.lib.read_one_external import read_one_external
from interactive_prompts.auth import create_jwt as create_interactive_prompt_jwt
from auth import auth_any
from itgs import Itgs
from models import STANDARD_ERRORS_BY_CODE


router = APIRouter()


@router.post(
    "/start_notification_time_prompt",
    status_code=200,
    response_model=ExternalInteractivePrompt,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def start_notification_time_prompt(authorization: Optional[str] = Header(None)):
    """Starts a new session in the interactive prompt where users can
    select when they want to receive notifications (and see when other
    users like to receive notifications!)

    Requires standard authorization, can be repeated any number of times
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        prompt_uid = await get_notification_time_prompt_uid(itgs)
        session_uid = f"oseh_ips_{secrets.token_urlsafe(16)}"
        prompt_jwt = await create_interactive_prompt_jwt(
            itgs, interactive_prompt_uid=prompt_uid
        )
        conn = await itgs.conn()
        cursor = conn.cursor()
        await cursor.execute(
            """
            INSERT INTO interactive_prompt_sessions (
                interactive_prompt_id, user_id, uid
            )
            SELECT
                interactive_prompts.id, users.id, ?
            FROM interactive_prompts, users
            WHERE
                interactive_prompts.uid = ?
                AND users.sub = ?
            """,
            (session_uid, prompt_uid, auth_result.result.sub),
        )

        return await read_one_external(
            itgs,
            interactive_prompt_uid=prompt_uid,
            interactive_prompt_jwt=prompt_jwt,
            interactive_prompt_session_uid=session_uid,
        )


async def get_notification_time_prompt_uid(itgs: Itgs) -> str:
    """Gets the UID of the interactive prompt that is shown as the control
    for when a user wants to receive notifications. This value is stored
    authoritatively in redis under `interactive_prompts:special:notification_time:uid`;
    if the value does not exist, a new prompt is created and the value is
    set to the new prompt's UID.

    The value is also locally cached in the
    `interactive_prompts:special:notification_time:uid` diskcache key after
    its been fetched.
    """
    locally_cached = await get_notification_time_prompt_uid_from_cache(itgs)
    if locally_cached is not None:
        return locally_cached

    redis_value = await get_notification_time_prompt_uid_from_redis(itgs)
    if redis_value is not None:
        await set_notification_time_prompt_uid_in_redis(itgs, redis_value)
        return redis_value

    new_prompt_uid = await create_notification_time_prompt(itgs)
    await set_notification_time_prompt_uid_in_redis(itgs, new_prompt_uid)
    await write_notification_time_prompt_uid_to_cache(itgs, new_prompt_uid)
    return new_prompt_uid


async def get_notification_time_prompt_uid_from_redis(itgs: Itgs) -> Optional[str]:
    redis = await itgs.redis()
    res: Optional[Union[str, bytes]] = await redis.get(
        b"interactive_prompts:special:notification_time:uid"
    )
    if res is None:
        return None
    if isinstance(res, bytes):
        return res.decode("utf-8")
    return res


async def set_notification_time_prompt_uid_in_redis(itgs: Itgs, uid: str) -> None:
    redis = await itgs.redis()
    await redis.set(
        b"interactive_prompts:special:notification_time:uid", uid.encode("utf-8")
    )


async def get_notification_time_prompt_uid_from_cache(itgs: Itgs) -> Optional[str]:
    cache = await itgs.local_cache()
    res: Optional[bytes] = cache.get(
        b"interactive_prompts:special:notification_time:uid"
    )
    if res is None:
        return None
    return res.decode("utf-8")


async def write_notification_time_prompt_uid_to_cache(itgs: Itgs, uid: str) -> None:
    cache = await itgs.local_cache()
    cache.set(
        b"interactive_prompts:special:notification_time:uid",
        uid.encode("utf-8"),
        expire=86400 + random.randrange(0, 86400),
    )


async def create_notification_time_prompt(itgs: Itgs) -> str:
    """Creates a new interactive prompt that can be used as the control
    for when a user wants to receive notifications, and returns the uid
    of the new interactive prompt.

    Args:
        itgs (Itgs): The integrations to (re)use

    Returns:
        str: The UID of the new interactive prompt
    """
    conn = await itgs.conn()
    cursor = conn.cursor()

    ip_uid = f"oseh_ip_{secrets.token_urlsafe(16)}"
    now = time.time()
    await cursor.execute(
        """
        INSERT INTO interactive_prompts (
            uid, prompt, duration_seconds, created_at, deleted_at
        )
        VALUES (?, ?, ?, ?, NULL)
        """,
        (
            ip_uid,
            json.dumps(
                {
                    "style": "word",
                    "text": "When do you want to receive text reminders?",
                    "options": ["Morning", "Afternoon", "Evening"],
                }
            ),
            20,
            now,
        ),
    )
    return ip_uid
