from typing import Any, Optional, List
import hashlib
import time
import redis.asyncio.client
from dataclasses import dataclass

SHARE_LINKS_VIEW_TO_LOG_INFO_LUA_SCRIPT = """
local views_to_log_length = redis.call("LLEN", "journey_share_links:views_to_log")
if views_to_log_length == 0 then
  return {0, false, false}
end

local first_uid = redis.call("LINDEX", "journey_share_links:views_to_log", 0)
local first_info = redis.call(
    "HMGET",
    "journey_share_links:views:" .. first_uid,
    "clicked_at",
    "confirmed_at"
)

return {views_to_log_length, first_info[1], first_info[2]}
"""

SHARE_LINKS_VIEW_TO_LOG_INFO_LUA_SCRIPT_HASH = hashlib.sha1(
    SHARE_LINKS_VIEW_TO_LOG_INFO_LUA_SCRIPT.encode("utf-8")
).hexdigest()


_last_share_links_view_to_log_info_ensured_at: Optional[float] = None


async def ensure_share_links_view_to_log_info_script_exists(
    redis: redis.asyncio.client.Redis, *, force: bool = False
) -> None:
    """Ensures the share_links_view_to_log_info lua script is loaded into redis."""
    global _last_share_links_view_to_log_info_ensured_at

    now = time.time()
    if (
        not force
        and _last_share_links_view_to_log_info_ensured_at is not None
        and (now - _last_share_links_view_to_log_info_ensured_at < 5)
    ):
        return

    loaded: List[bool] = await redis.script_exists(
        SHARE_LINKS_VIEW_TO_LOG_INFO_LUA_SCRIPT_HASH
    )
    if not loaded[0]:
        correct_hash = await redis.script_load(SHARE_LINKS_VIEW_TO_LOG_INFO_LUA_SCRIPT)
        assert (
            correct_hash == SHARE_LINKS_VIEW_TO_LOG_INFO_LUA_SCRIPT_HASH
        ), f"{correct_hash=} != {SHARE_LINKS_VIEW_TO_LOG_INFO_LUA_SCRIPT_HASH=}"

    if (
        _last_share_links_view_to_log_info_ensured_at is None
        or _last_share_links_view_to_log_info_ensured_at < now
    ):
        _last_share_links_view_to_log_info_ensured_at = now


@dataclass
class ShareLinksViewToLogInfoResult:
    length: int
    """llen of journey_share_links:views_to_log"""
    first_clicked_at: Optional[float]
    """
    The clicked_at timestamp of the first item in journey_share_links:views_to_log,
    if applicable
    """
    first_confirmed_at: Optional[float]
    """
    The confirmed_at timestamp of the first item in journey_share_links:views_to_log,
    if applicable
    """


async def share_links_view_to_log_info(
    redis: redis.asyncio.client.Redis,
) -> Optional[ShareLinksViewToLogInfoResult]:
    """Fetches information about the journey share links views_to_log list from redis,
    fetching info about the first item in the list if applicable.

    Args:
        redis (redis.asyncio.client.Redis): The redis client

    Returns:
        ShareLinksViewToLogInfoResult, None: The information. None if executed
            within a transaction, since the result is not known until the
            transaction is executed.

    Raises:
        NoScriptError: If the script is not loaded into redis
    """
    res = await redis.evalsha(SHARE_LINKS_VIEW_TO_LOG_INFO_LUA_SCRIPT_HASH, 0)  # type: ignore
    if res is redis:
        return None
    return parse_share_links_view_to_log_info_result(res)


def parse_share_links_view_to_log_info_result(
    res: Any,
) -> ShareLinksViewToLogInfoResult:
    """Parses the result of the share_links_view_to_log_info lua script."""
    assert isinstance(res, list), f"{res=}"
    assert len(res) == 3, f"{res=}"
    assert isinstance(res[0], int), f"{res=}"
    assert isinstance(res[1], (bytes, type(None))), f"{res=}"
    assert isinstance(res[2], (bytes, type(None))), f"{res=}"

    return ShareLinksViewToLogInfoResult(
        length=res[0],
        first_clicked_at=None if res[1] is None else float(res[1]),
        first_confirmed_at=None if res[2] is None else float(res[2]),
    )
