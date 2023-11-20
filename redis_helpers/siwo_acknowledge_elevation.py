from typing import Literal, Optional, List, Union
import hashlib
import time
import redis.asyncio.client
from dataclasses import dataclass
import unix_dates
import pytz

SIWO_ACKNOWLEDGE_ELEVATION_LUA_SCRIPT = """
local email = ARGV[1]
local delay = tonumber(ARGV[2])
local acknowledged_at = tonumber(ARGV[3])
local code_to_send = ARGV[4]
local code_to_store = ARGV[5]
local email_uid = ARGV[6]
local email_log_entry_uid = ARGV[7]
local reason = ARGV[8]
local acknowledged_unix_date = tonumber(ARGV[9])
local midnight_next_day = tonumber(ARGV[10])

local email_codes_key = 'sign_in_with_oseh:security_checks:' .. email
redis.call("zremrangebyscore", email_codes_key, "-inf", tostring(acknowledged_at - 60 * 60 * 24))

local num_recent_codes = redis.call("ZCOUNT", email_codes_key, tostring(acknowledged_at - 60), "+inf")
if num_recent_codes > 0 then
    return {-1, false}
end

local email_queued_at = acknowledged_at
if delay <= 0 then
    local email_to_send_length = redis.call("LLEN", "email:to_send")
    if email_to_send_length >= 1000 then
        return {-2, false}
    end
else
    local delayed_length = redis.call("ZCARD", "sign_in_with_oseh:delayed_emails")
    if delayed_length >= 1000 then
        return {-3, false}
    end

    local min_delay_start_key = "sign_in_with_oseh:min_delay_start"
    local min_delay_start = redis.call("GET", min_delay_start_key)
    if min_delay_start == false then
        min_delay_start = 0
    else
        min_delay_start = tonumber(min_delay_start)
    end

    if min_delay_start < acknowledged_at then
        min_delay_start = acknowledged_at
    end

    if min_delay_start + delay > acknowledged_at + 60 * 25 then
        return {-4, false}
    end

    redis.call("SET", min_delay_start_key, tostring(min_delay_start + 5))
    redis.call("EXPIREAT", min_delay_start_key, math.ceil(min_delay_start + 5))
    email_queued_at = min_delay_start + delay
end

local email_to_send = cjson.encode({
    aud = "send",
    uid = email_uid,
    email = email,
    subject = "Your security code",
    template = "verifyEmailCode",
    template_parameters = {
        code = code_to_send,
    },
    initially_queued_at = email_queued_at,
    retry = 0,
    last_queued_at = email_queued_at,
    failure_job = {
        name = "runners.siwo.email_failure_handler",
        kwargs = {
            uid = email_log_entry_uid
        }
    },
    success_job = {
        name = "runners.siwo.email_success_handler",
        kwargs = {
            uid = email_log_entry_uid
        }
    }
})

redis.call("ZADD", email_codes_key, tostring(email_queued_at), code_to_store)

local current_ttl = redis.call("TTL", email_codes_key)
local target_min_ttl = math.ceil(email_queued_at + 60 * 60 * 24)
if current_ttl < target_min_ttl then
    redis.call("EXPIREAT", email_codes_key, target_min_ttl)
end

redis.call(
    "HSET", 
    "sign_in_with_oseh:security_checks:" .. email .. ":codes:" .. code_to_store,
    "acknowledged_at", tostring(acknowledged_at),
    "delayed", delay > 0 and "1" or "0",
    "bogus", code_to_store ~= code_to_send and "1" or "0",
    "sent_at", tostring(email_queued_at),
    "expires_at", tostring(email_queued_at + 60 * 30),
    "reason", reason,
    "already_used", "0"
)
redis.call(
    "EXPIREAT",
    "sign_in_with_oseh:security_checks:" .. email .. ":codes:" .. code_to_store,
    math.ceil(email_queued_at + 60 * 60 * 24)
)

local send_unix_date = acknowledged_unix_date
if email_queued_at >= midnight_next_day then
    send_unix_date = send_unix_date + 1
end

local stats_key = "stats:email_send:daily:" .. tostring(send_unix_date)
local earliest_key = "stats:email_send:daily:earliest"

local old_earliest = redis.call("GET", earliest_key)
if old_earliest == false or tonumber(old_earliest) > send_unix_date then
    redis.call("SET", earliest_key, tostring(send_unix_date))
end

redis.call("HINCRBY", stats_key, "queued", 1)

if delay <= 0 then
    redis.call("RPUSH", "email:to_send", email_to_send)
    return {1, false}
else
    redis.call("ZADD", "sign_in_with_oseh:delayed_emails", tostring(email_queued_at), email_to_send)
    return  {2, tostring(email_queued_at)}
end
"""

SIWO_ACKNOWLEDGE_ELEVATION_LUA_SCRIPT_HASH = hashlib.sha1(
    SIWO_ACKNOWLEDGE_ELEVATION_LUA_SCRIPT.encode("utf-8")
).hexdigest()


_last_siwo_acknowledge_elevation_ensured_at: Optional[float] = None


async def ensure_siwo_acknowledge_elevation_script_exists(
    redis: redis.asyncio.client.Redis, *, force: bool = False
) -> None:
    """Ensures the siwo_acknowledge_elevation lua script is loaded into redis."""
    global _last_siwo_acknowledge_elevation_ensured_at

    now = time.time()
    if (
        not force
        and _last_siwo_acknowledge_elevation_ensured_at is not None
        and (now - _last_siwo_acknowledge_elevation_ensured_at < 5)
    ):
        return

    loaded: List[bool] = await redis.script_exists(
        SIWO_ACKNOWLEDGE_ELEVATION_LUA_SCRIPT_HASH
    )
    if not loaded[0]:
        correct_hash = await redis.script_load(SIWO_ACKNOWLEDGE_ELEVATION_LUA_SCRIPT)
        assert (
            correct_hash == SIWO_ACKNOWLEDGE_ELEVATION_LUA_SCRIPT_HASH
        ), f"{correct_hash=} != {SIWO_ACKNOWLEDGE_ELEVATION_LUA_SCRIPT_HASH=}"

    if (
        _last_siwo_acknowledge_elevation_ensured_at is None
        or _last_siwo_acknowledge_elevation_ensured_at < now
    ):
        _last_siwo_acknowledge_elevation_ensured_at = now


@dataclass
class SiwoAcknowledgeElevationResult:
    action: Literal["sent", "delayed", "unsent"]
    """What action was performed, where:
    
    - `sent`: the email was sent immediately
    - `delayed`: the email was delayed
    - `unsent`: the email was not sent
    """

    reason: Optional[
        Literal[
            "ratelimited",
            "backpressure:email_to_send",
            "backpressure:delayed:total",
            "backpressure:delayed:duration",
        ]
    ]
    """The reason the email was not sent, if any. Where:

    - `ratelimited`: we have sent too many verification codes to this email address
        recently
    - `backpressure:email_to_send`: we have too many emails queued to send
    - `backpressure:delayed:total`: we have too many emails delayed
    - `backpressure:delayed:duration`: by the time we would have sent the email,
      the code would be nearly expired
    """

    send_target_at: Optional[float]
    """
    If the email was delayed, when we scheduled it to be sent, in seconds since 
    the unix epoch
    """


async def siwo_acknowledge_elevation(
    redis: redis.asyncio.client.Redis,
    email: Union[str, bytes],
    delay: float,
    acknowledged_at: float,
    code_to_send: Union[str, bytes],
    code_to_store: Union[str, bytes],
    email_uid: Union[str, bytes],
    email_log_entry_uid: Union[str, bytes],
    reason: Union[str, bytes],
) -> Optional[SiwoAcknowledgeElevationResult]:
    """Handles the user acknowledging the elevation requirement to check the
    account with the given email address. Sends the user an email with the
    `code_to_send` verification code and stores `code_to_store` for later lookup.
    If the two codes match, that means the user can provide the code to check
    the account, if the two codes mismatch, if the user does provide the stored
    code it means we detected they are using some other technique to get codes
    (e.g., guessing them).

    Args:
        redis (redis.asyncio.client.Redis): The redis client
        email (str, bytes): the email being checked
        delay (float): how long to wait at minimum before sending the verification
            email. Can be used as a ratelimiting measure; if this is set to 0, the
            email is sent as soon as possible. Otherwise, we have a minimum time
            between emails of 5 seconds, and then from that base time we add the
            delay.
        acknowledged_at (float): when the user acknowledged the elevation request,
            in seconds since the epoch
        code_to_send (str, bytes): the code to send to the user
        code_to_store (str, bytes): the code to store for later lookup
        email_uid (str, bytes): the uid of the email to eventually add to the email:to_send
            queue. This should generally just be the result of create_email_uid, which is not
            available in redis
        email_log_entry_uid (str, bytes): The uid of the row in `siwo_email_log` to update
            if the email succeeds/fails
        reason (str, bytes): the reason we elevated the request in the first place

    Returns:
        SiwoAcknowledgeElevationResult, None: What action was took any why. None
            if executed within a transaction, since the result is not known
            until the transaction is executed.

    Raises:
        NoScriptError: If the script is not loaded into redis
    """
    tz = pytz.timezone("America/Los_Angeles")
    acknowledged_unix_date = unix_dates.unix_timestamp_to_unix_date(
        acknowledged_at, tz=tz
    )
    midnight_next_day = unix_dates.unix_date_to_timestamp(
        acknowledged_unix_date + 1, tz=tz
    )
    res = await redis.evalsha(  # type: ignore
        SIWO_ACKNOWLEDGE_ELEVATION_LUA_SCRIPT_HASH,
        0,
        email,  # type: ignore
        str(delay).encode("utf-8"),  # type: ignore
        str(acknowledged_at).encode("utf-8"),  # type: ignore
        code_to_send,  # type: ignore
        code_to_store,  # type: ignore
        email_uid,  # type: ignore
        email_log_entry_uid,  # type: ignore
        reason,  # type: ignore
        str(acknowledged_unix_date).encode("utf-8"),  # type: ignore
        str(midnight_next_day).encode("utf-8"),  # type: ignore
    )
    if res is redis:
        return None
    return parse_siwo_acknowledge_elevation_result(res)


parser_by_status = {
    -1: lambda send_target_at: SiwoAcknowledgeElevationResult(
        action="unsent", reason="ratelimited", send_target_at=None
    ),
    -2: lambda send_target_at: SiwoAcknowledgeElevationResult(
        action="unsent", reason="backpressure:email_to_send", send_target_at=None
    ),
    -3: lambda send_target_at: SiwoAcknowledgeElevationResult(
        action="unsent", reason="backpressure:delayed:total", send_target_at=None
    ),
    -4: lambda send_target_at: SiwoAcknowledgeElevationResult(
        action="unsent", reason="backpressure:delayed:duration", send_target_at=None
    ),
    1: lambda send_target_at: SiwoAcknowledgeElevationResult(
        action="sent", reason=None, send_target_at=None
    ),
    2: lambda send_target_at: SiwoAcknowledgeElevationResult(
        action="delayed", reason=None, send_target_at=float(send_target_at)
    ),
}


def parse_siwo_acknowledge_elevation_result(res) -> SiwoAcknowledgeElevationResult:
    """Parses the redis response from the script into our
    interpreted variant.
    """
    assert isinstance(res, list)

    status = res[0]
    send_target_at = res[1]
    assert isinstance(status, int)
    assert isinstance(send_target_at, (str, bytes, type(None)))
    return parser_by_status[status](res[1])
