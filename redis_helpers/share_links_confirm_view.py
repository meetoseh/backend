from typing import Any, Optional, List, Literal, Union
import hashlib
import time
import redis.asyncio.client
from dataclasses import dataclass

SHARE_LINKS_CONFIRM_VIEW_LUA_SCRIPT = """
local view_uid = ARGV[1]
local user_sub = ARGV[2]
local visitor = ARGV[3]
local confirmed_at = tonumber(ARGV[4])

local pseudoset_key = "journey_share_links:views:" .. view_uid
local existing_confirmed_at = redis.call("HGET", pseudoset_key, "confirmed_at")
if existing_confirmed_at ~= false and existing_confirmed_at ~= "" then
    return {-1}
end

if existing_confirmed_at == false and redis.call("EXISTS", pseudoset_key) == 0 then
    return {-2}
end

local in_purgatory = redis.call("SISMEMBER", "journey_share_links:views_log_purgatory", view_uid)
if in_purgatory == 1 then
    local journey_share_link_uid = redis.call("HGET", pseudoset_key, "journey_share_link_uid")
    if journey_share_link_uid == false or journey_share_link_uid == "" then
        return {-3}
    end

    local in_views_to_confirm = redis.call("HEXISTS", "journey_share_links:views_to_confirm", view_uid)
    if in_views_to_confirm == 1 then
        return {-4}
    end

    redis.call("HSET", "journey_share_links:views_to_confirm", view_uid, cjson.encode({
        uid = view_uid,
        user_sub = user_sub,
        visitor = visitor,
        confirmed_at = confirmed_at
    }))

    local journey_share_link_code = redis.call("HGET", pseudoset_key, "journey_share_link_code")
    return {100, journey_share_link_code, journey_share_link_uid}
end


redis.call("HSET", pseudoset_key, "user_sub", user_sub, "visitor", visitor, "confirmed_at", confirmed_at)
redis.call("ZREM", "journey_share_links:views_unconfirmed", view_uid)
redis.call("RPUSH", "journey_share_links:views_to_log", view_uid)

local journey_share_link_code = redis.call("HGET", pseudoset_key, "journey_share_link_code")
local journey_share_link_uid = redis.call("HGET", pseudoset_key, "journey_share_link_uid")
return {101, journey_share_link_code, journey_share_link_uid}
"""

SHARE_LINKS_CONFIRM_VIEW_LUA_SCRIPT_HASH = hashlib.sha1(
    SHARE_LINKS_CONFIRM_VIEW_LUA_SCRIPT.encode("utf-8")
).hexdigest()


_last_share_links_confirm_view_ensured_at: Optional[float] = None


async def ensure_share_links_confirm_view_script_exists(
    redis: redis.asyncio.client.Redis, *, force: bool = False
) -> None:
    """Ensures the share_links_confirm_view lua script is loaded into redis."""
    global _last_share_links_confirm_view_ensured_at

    now = time.time()
    if (
        not force
        and _last_share_links_confirm_view_ensured_at is not None
        and (now - _last_share_links_confirm_view_ensured_at < 5)
    ):
        return

    loaded: List[bool] = await redis.script_exists(
        SHARE_LINKS_CONFIRM_VIEW_LUA_SCRIPT_HASH
    )
    if not loaded[0]:
        correct_hash = await redis.script_load(SHARE_LINKS_CONFIRM_VIEW_LUA_SCRIPT)
        assert (
            correct_hash == SHARE_LINKS_CONFIRM_VIEW_LUA_SCRIPT_HASH
        ), f"{correct_hash=} != {SHARE_LINKS_CONFIRM_VIEW_LUA_SCRIPT_HASH=}"

    if (
        _last_share_links_confirm_view_ensured_at is None
        or _last_share_links_confirm_view_ensured_at < now
    ):
        _last_share_links_confirm_view_ensured_at = now


@dataclass
class ShareLinkConfirmViewFailureResult:
    success: Literal[False]
    details: Literal[
        "already_confirmed",
        "not_in_pseudoset",
        "in_purgatory_but_invalid",
        "in_purgatory_and_already_confirmed",
    ]
    """Why we failed to confirm the view within redis; one of:

    - `already_confirmed`: The view has already been confirmed
    - `not_in_pseudoset`: The view is not in redis; the uid is either invalid
      or has already been persisted
    - `in_purgatory_but_invalid`: The view exists in the pseudoset. The share
      link view job is already working on it, and the code related to the view
      was invalid. We only put this view in the pseudoset to see if it was
      confirmed in time to reduce the ratelimiting penalty, and it was not, 
      so we can just drop the confirmation.
    - `in_purgatory_and_already_confirmed`: The view exists in the pseudoset,
      and the link view persist job is already working on it. This means we can't modify
      the pseudoset. However it was already confirmed in the past while it was
      being worked on by the link view persist job: at that time we could not
      modify the pseudoset since the persist job may have already read the value
      from the pseudoset (hence we didn't fail with already_confirmed) so we instead
      stored in the raced confirmations hash. During this request we found the
      view in the raced confirmations hash.
    """


@dataclass
class ShareLinkConfirmViewSuccessResult:
    success: Literal[True]
    details: Literal["in_purgatory", "standard"]
    """
    - `in_purgatory`: The view was in the pseudoset, but the link view
      persist job was already working on it. So we couldn't modify the
      pseudoset directly; we instead stored the confirmation in the raced
      confirmations hash.
    - `standard`: The view was in the pseudoset, unconfirmed, and not being
      worked on by the link view persist job. We mutated the pseudoset directly
    """
    link_code: str
    """The link code associated with the view"""
    link_uid: Optional[str]
    """
    The link uid associated with the view, if the code was valid at the time
    it was hydrated
    """


ShareLinkConfirmViewResult = Union[
    ShareLinkConfirmViewFailureResult, ShareLinkConfirmViewSuccessResult
]


async def share_links_confirm_view(
    redis: redis.asyncio.client.Redis,
    view_uid: str,
    user_sub: Optional[str],
    visitor: Optional[str],
    confirmed_at: float,
) -> Optional[ShareLinkConfirmViewResult]:
    """Confirms the view of a share link if it is in redis and not already
    confirmed.

    Args:
        redis (redis.asyncio.client.Redis): The redis client
        view_uid (str): The uid of the view to confirm
        user_sub (str, None): The sub of the user who viewed the link, if
            known
        visitor (str, None): The visitor who viewed the link, if known
        confirmed_at (float): The unix timestamp when the view was confirmed

    Returns:
        ShareLinkConfirmViewResult, None: What occurred. None if executed
            within a transaction, since the result is not known until the
            transaction is executed.

    Raises:
        NoScriptError: If the script is not loaded into redis
    """
    res = await redis.evalsha(
        SHARE_LINKS_CONFIRM_VIEW_LUA_SCRIPT_HASH,
        0,
        view_uid.encode("utf-8"),  # type: ignore
        user_sub.encode("utf-8") if user_sub is not None else b"",  # type: ignore
        visitor.encode("utf-8") if visitor is not None else b"",  # type: ignore
        str(confirmed_at).encode("utf-8"),  # type: ignore
    )
    if res is redis:
        return None
    return parse_share_links_confirm_view_result(res)


def parse_share_links_confirm_view_result(result: Any) -> ShareLinkConfirmViewResult:
    """Parses the result from the redis script into a more useful format"""
    assert isinstance(result, list), result
    assert len(result) > 0, result
    result_type = result[0]
    if result_type == -1:
        assert len(result) == 1, result
        return ShareLinkConfirmViewFailureResult(
            success=False, details="already_confirmed"
        )
    elif result_type == -2:
        assert len(result) == 1, result
        return ShareLinkConfirmViewFailureResult(
            success=False, details="not_in_pseudoset"
        )
    elif result_type == -3:
        assert len(result) == 1, result
        return ShareLinkConfirmViewFailureResult(
            success=False, details="in_purgatory_but_invalid"
        )
    elif result_type == -4:
        assert len(result) == 1, result
        return ShareLinkConfirmViewFailureResult(
            success=False, details="in_purgatory_and_already_confirmed"
        )
    elif result_type == 100:
        assert len(result) == 3, result
        assert isinstance(result[1], bytes), result
        assert isinstance(result[2], bytes), result
        return ShareLinkConfirmViewSuccessResult(
            success=True,
            details="in_purgatory",
            link_code=result[1].decode("utf-8"),
            link_uid=result[2].decode("utf-8"),
        )
    elif result_type == 101:
        assert len(result) == 3, result
        assert isinstance(result[1], bytes), result
        assert isinstance(result[2], Optional[bytes]), result
        return ShareLinkConfirmViewSuccessResult(
            success=True,
            details="standard",
            link_code=result[1].decode("utf-8"),
            link_uid=result[2].decode("utf-8") if result[2] is not None else None,
        )

    raise ValueError(f"Unexpected result from share_links_confirm_view: {result=}")
