from typing import Optional, List
import hashlib
import time
import redis.asyncio.client

SHARE_LINKS_HANDLE_VISITOR_VIEW_LUA_SCRIPT = """
local unix_date = ARGV[1]
local visitor_uid = ARGV[2]
local code = ARGV[3]
local journey_subcategory_internal_name = ARGV[4]
local sharer_sub = ARGV[5]
local view_uid = ARGV[6]

local pseudoset_key = "journey_share_links:views:" .. view_uid
local raced_confirmations_key = "journey_share_links:views_to_confirm"

local view_in_pseudoset = redis.call("EXISTS", pseudoset_key) == 1
local view_in_purgatory = redis.call("HEXISTS", "journey_share_links:views_log_purgatory", view_uid) == 1
local view_in_raced_confirmations = false
if view_in_purgatory then
    view_in_raced_confirmations = redis.call("HEXISTS", raced_confirmations_key, view_uid) == 1
end

local sadd_result = redis.call("SADD", "journey_share_links:visitors:" .. unix_date, visitor_uid)
if sadd_result == 0 then 
    if view_in_pseudoset and not view_in_purgatory then
        redis.call("HSET", pseudoset_key, "visitor_was_unique", "0")
    elseif view_in_raced_confirmations then
        local info = redis.call("HGET", raced_confirmations_key, view_uid)
        local parsed_info = cjson.decode(info)
        parsed_info["visitor_was_unique"] = "0"
        redis.call("HSET", raced_confirmations_key, view_uid, cjson.encode(parsed_info))
    end
    return 0 
end

redis.call("INCR", "stats:journey_share_links:unique_views:count")
if view_in_pseudoset and not view_in_purgatory then
    redis.call("HSET", pseudoset_key, "visitor_was_unique", "1")
elseif view_in_raced_confirmations then
    local info = redis.call("HGET", raced_confirmations_key, view_uid)
    local parsed_info = cjson.decode(info)
    parsed_info["visitor_was_unique"] = "1"
    redis.call("HSET", raced_confirmations_key, view_uid, cjson.encode(parsed_info))
end

local earliest_key = "stats:journey_share_links:unique_views:daily:earliest"
local old_earliest = redis.call("GET", earliest_key)
if old_earliest == false or tonumber(old_earliest) > tonumber(unix_date) then
    redis.call("SET", earliest_key, unix_date)
end

local counts_key = "stats:journey_share_links:unique_views:daily:" .. unix_date
redis.call("HINCRBY", counts_key, "by_code", "1")
redis.call("HINCRBY", counts_key .. ":extra:by_code", code, "1")
redis.call("HINCRBY", counts_key, "by_journey_subcategory", "1")
redis.call("HINCRBY", counts_key .. ":extra:by_journey_subcategory", journey_subcategory_internal_name, "1")

if sharer_sub ~= "" then
    redis.call("HINCRBY", counts_key, "by_sharer_sub", "1")
    redis.call("HINCRBY", counts_key .. ":extra:by_sharer_sub", sharer_sub, "1")
end

return 1
"""

SHARE_LINKS_HANDLE_VISITOR_VIEW_LUA_SCRIPT_HASH = hashlib.sha1(
    SHARE_LINKS_HANDLE_VISITOR_VIEW_LUA_SCRIPT.encode("utf-8")
).hexdigest()


_last_share_links_handle_visitor_view_ensured_at: Optional[float] = None


async def ensure_share_links_handle_visitor_view_script_exists(
    redis: redis.asyncio.client.Redis, *, force: bool = False
) -> None:
    """Ensures the share_links_handle_visitor_view lua script is loaded into redis."""
    global _last_share_links_handle_visitor_view_ensured_at

    now = time.time()
    if (
        not force
        and _last_share_links_handle_visitor_view_ensured_at is not None
        and (now - _last_share_links_handle_visitor_view_ensured_at < 5)
    ):
        return

    loaded: List[bool] = await redis.script_exists(
        SHARE_LINKS_HANDLE_VISITOR_VIEW_LUA_SCRIPT_HASH
    )
    if not loaded[0]:
        correct_hash = await redis.script_load(
            SHARE_LINKS_HANDLE_VISITOR_VIEW_LUA_SCRIPT
        )
        assert (
            correct_hash == SHARE_LINKS_HANDLE_VISITOR_VIEW_LUA_SCRIPT_HASH
        ), f"{correct_hash=} != {SHARE_LINKS_HANDLE_VISITOR_VIEW_LUA_SCRIPT_HASH=}"

    if (
        _last_share_links_handle_visitor_view_ensured_at is None
        or _last_share_links_handle_visitor_view_ensured_at < now
    ):
        _last_share_links_handle_visitor_view_ensured_at = now


async def share_links_handle_visitor_view(
    redis: redis.asyncio.client.Redis,
    unix_date: int,
    visitor_uid: bytes,
    code: bytes,
    journey_subcategory_internal_name: bytes,
    sharer_sub: Optional[bytes],
    view_uid: bytes,
) -> Optional[bool]:
    """Adds the visitor to the visitors set for the given date. If the visitor was
    not already in the set, updates `stats:journey_share_links:unique_views:daily:earliest` to the
    lower of its current value and the provided unix date and returns true. Otherwise,
    when the visitor was already in the set, returns false.

    If the visitor was not already in the set, increments the appropriate
    fields and breakdowns in `stats:journey_share_links:unique_views:daily:{unix_date}`
    and will update the `visitor_was_unique` value in the view pseudoset if the view
    is still in the view pseudoset.

    Args:
        redis (redis.asyncio.client.Redis): The redis client
        unix_date (int): The unix date
        visitor_uid (bytes): The uid of the visitor who saw journey share link
        code (bytes): The code of the journey share link
        journey_subcategory_internal_name (bytes): The internal name of the journey subcategory
        sharer_sub (Optional[bytes]): The sharer user sub, if known
        view_uid (bytes): the uid of the view for which we saw this visitor

    Returns:
        bool, None: The information. True if the visitor was not in the set,
          false if the visitor was in the set. None if executed
          within a transaction, since the result is not known until the
          transaction is executed.

    Raises:
        NoScriptError: If the script is not loaded into redis
    """
    res = await redis.evalsha(
        SHARE_LINKS_HANDLE_VISITOR_VIEW_LUA_SCRIPT_HASH,
        0,
        str(unix_date).encode("ascii"),  # type: ignore
        visitor_uid,  # type: ignore
        code,  # type: ignore
        journey_subcategory_internal_name,  # type: ignore
        sharer_sub if sharer_sub is not None else b"",  # type: ignore
        view_uid,  # type: ignore
    )
    if res is redis:
        return None
    return bool(res)
