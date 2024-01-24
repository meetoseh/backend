from typing import Optional, List, Tuple, cast
import hashlib
import time
import redis.asyncio.client

SHARE_LINKS_COUNT_ATTRIBUTABLE_USERS_LUA_SCRIPT = """
local start_unix_date_incl = tonumber(ARGV[1])
local end_unix_date_excl = tonumber(ARGV[2])
local cursor_unix_date = tonumber(ARGV[3])
local cursor_for_next_utms = tonumber(ARGV[4])

local next_unix_date = start_unix_date_incl + cursor_unix_date

if next_unix_date >= end_unix_date_excl then
  return {0,0,0}
end

local result = 0

for outer_iteration = 1, 10 do
    local next_unix_date_str = tostring(next_unix_date)
    local sscan_result = redis.call(
        "SSCAN",
        "stats:visitors:daily:" .. next_unix_date_str .. ":utms",
        cursor_for_next_utms,
        "MATCH",
        "utm_campaign=share_link&utm_medium=referral&utm_source=oseh_app*"
    )

    cursor_for_next_utms = tonumber(sscan_result[1])
    local utms = sscan_result[2]

    for _, utm in ipairs(utms) do
        local utm_result = redis.call(
            "HMGET",
            "stats:visitors:daily:" .. utm .. ":" .. next_unix_date_str .. ":counts",
            "holdover_any_click_signups",
            "any_click_signups"
        )

        if utm_result[1] ~= false and utm_result[1] ~= "" then
            result = result + tonumber(utm_result[1])
        end

        if utm_result[2] ~= false and utm_result[2] ~= "" then
            result = result + tonumber(utm_result[2])
        end
    end

    if cursor_for_next_utms == 0 then
        cursor_unix_date = cursor_unix_date + 1
        next_unix_date = next_unix_date + 1
        if next_unix_date >= end_unix_date_excl then
            return {0, 0, result}
        end
    end
end

return {cursor_unix_date, cursor_for_next_utms, result}
"""

SHARE_LINKS_COUNT_ATTRIBUTABLE_USERS_LUA_SCRIPT_HASH = hashlib.sha1(
    SHARE_LINKS_COUNT_ATTRIBUTABLE_USERS_LUA_SCRIPT.encode("utf-8")
).hexdigest()


_last_share_links_count_attributable_users_ensured_at: Optional[float] = None


async def ensure_share_links_count_attributable_users_script_exists(
    redis: redis.asyncio.client.Redis, *, force: bool = False
) -> None:
    """Ensures the share_links_count_attributable_users lua script is loaded into redis."""
    global _last_share_links_count_attributable_users_ensured_at

    now = time.time()
    if (
        not force
        and _last_share_links_count_attributable_users_ensured_at is not None
        and (now - _last_share_links_count_attributable_users_ensured_at < 5)
    ):
        return

    loaded: List[bool] = await redis.script_exists(
        SHARE_LINKS_COUNT_ATTRIBUTABLE_USERS_LUA_SCRIPT_HASH
    )
    if not loaded[0]:
        correct_hash = await redis.script_load(
            SHARE_LINKS_COUNT_ATTRIBUTABLE_USERS_LUA_SCRIPT
        )
        assert (
            correct_hash == SHARE_LINKS_COUNT_ATTRIBUTABLE_USERS_LUA_SCRIPT_HASH
        ), f"{correct_hash=} != {SHARE_LINKS_COUNT_ATTRIBUTABLE_USERS_LUA_SCRIPT_HASH=}"

    if (
        _last_share_links_count_attributable_users_ensured_at is None
        or _last_share_links_count_attributable_users_ensured_at < now
    ):
        _last_share_links_count_attributable_users_ensured_at = now


async def share_links_count_attributable_users(
    redis: redis.asyncio.client.Redis,
    start_unix_date_incl: int,
    end_unix_date_excl: int,
    cursor_unix_date: int,
    cursor_utms_on_date: int,
) -> Optional[Tuple[int, int, int]]:
    """Looks through the utm statistics that are in redis and counts the number of
    users attributable to the UTM associated with share links. This limits the amount
    of work per call to at most 100 different utms, but can split the work across
    multiple dates.

    Args:
        redis (redis.asyncio.client.Redis): The redis client
        start_unix_date_incl (int): The unix date to start counting from, inclusive
        end_unix_date_excl (int): The unix date to stop counting at, exclusive
        cursor_unix_date (int): The cursor for the current unix date. This should start
            at 0, and iteration is not finished until both cursors are 0.
        cursor_utms_on_date (int): The cursor for the current utms on the current date.
            This should start at 0, and iteration is not finished until both cursors
            are 0.

    Returns:
        (int, int, int), None: (cursor_unix_date, cursor_utms_on_date, result) if
            not in a pipeline, else None

    Raises:
        NoScriptError: If the script is not loaded into redis
    """
    res = await redis.evalsha(SHARE_LINKS_COUNT_ATTRIBUTABLE_USERS_LUA_SCRIPT_HASH, 0, start_unix_date_incl, end_unix_date_excl, cursor_unix_date, cursor_utms_on_date)  # type: ignore
    if res is redis:
        return None
    return cast(Tuple[int, int, int], tuple(cast(List[int], res)))
