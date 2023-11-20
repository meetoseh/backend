from typing import Literal, Optional, List, Tuple, Union, cast as typing_cast
import hashlib
import time
import redis.asyncio.client
from pydantic import BaseModel, Field

SIWO_CHECK_SECURITY_CODE_LUA_SCRIPT = """
local email = ARGV[1]
local code = ARGV[2]
local now = tonumber(ARGV[3])

local codes_for_email_key = "sign_in_with_oseh:security_checks:" .. email

local rank_result = redis.call("ZRANK", codes_for_email_key, code)
if rank_result == false then return {-1, false} end

local hidden_key = "sign_in_with_oseh:security_checks:" .. email .. ":codes:" .. code
local hidden_type = redis.call("TYPE", hidden_key)['ok']
if hidden_type ~= "hash" then return {-2, false} end

local bogus = redis.call("HGET", hidden_key, "bogus")
if bogus == "1" then return {-3, false} end

local already_used = redis.call("HGET", hidden_key, "already_used")
if already_used == "1" then return {-4, false} end

local expires_at = tonumber(redis.call("HGET", hidden_key, "expires_at"))
if expires_at < now then return {-5, false} end

local number_of_codes = redis.call("ZCARD", codes_for_email_key)
if number_of_codes ~= rank_result + 1 then return {-6, false} end

local sent_at = tonumber(redis.call("HGET", hidden_key, "sent_at"))
if sent_at > now + 1 then return {-7, false} end

redis.call("HSET", hidden_key, "already_used", "1")
return {1, redis.call("HMGET", hidden_key, "acknowledged_at", "delayed", "sent_at", "reason")}
"""

SIWO_CHECK_SECURITY_CODE_LUA_SCRIPT_HASH = hashlib.sha1(
    SIWO_CHECK_SECURITY_CODE_LUA_SCRIPT.encode("utf-8")
).hexdigest()


_last_siwo_check_security_code_ensured_at: Optional[float] = None


async def ensure_siwo_check_security_code_script_exists(
    redis: redis.asyncio.client.Redis, *, force: bool = False
) -> None:
    """Ensures the siwo_check_security_code lua script is loaded into redis."""
    global _last_siwo_check_security_code_ensured_at

    now = time.time()
    if (
        not force
        and _last_siwo_check_security_code_ensured_at is not None
        and (now - _last_siwo_check_security_code_ensured_at < 5)
    ):
        return

    loaded: List[bool] = await redis.script_exists(
        SIWO_CHECK_SECURITY_CODE_LUA_SCRIPT_HASH
    )
    if not loaded[0]:
        correct_hash = await redis.script_load(SIWO_CHECK_SECURITY_CODE_LUA_SCRIPT)
        assert (
            correct_hash == SIWO_CHECK_SECURITY_CODE_LUA_SCRIPT_HASH
        ), f"{correct_hash=} != {SIWO_CHECK_SECURITY_CODE_LUA_SCRIPT_HASH=}"

    if (
        _last_siwo_check_security_code_ensured_at is None
        or _last_siwo_check_security_code_ensured_at < now
    ):
        _last_siwo_check_security_code_ensured_at = now


SiwoCheckSecurityCodeStatus = Literal[
    "valid",
    "bogus",
    "lost",
    "already_used",
    "expired",
    "unknown",
    "revoked",
    "not_sent_yet",
]


SiwoSecurityCodeHiddenInfoReason = Literal[
    "visitor",
    "email",
    "global",
    "ratelimit",
    "email_ratelimit",
    "visitor_ratelimit",
    "strange",
    "disposable",
]


class SiwoSecurityCodeHiddenInfo(BaseModel):
    acknowledged_at: float = Field(
        description="when the user acknowledged the elevation request, in seconds since the epoch"
    )
    delayed: bool = Field(
        description="true if we purposely delayed sending them the verification email, false if we did not purposely delay sending the email"
    )
    sent_at: float = Field(
        description="when we intended for the email to be sent, in seconds since the epoch"
    )
    reason: SiwoSecurityCodeHiddenInfoReason = Field(
        description="the reason we sent them this code in the first place"
    )


SiwoCheckSecurityCodeResult = Tuple[
    SiwoCheckSecurityCodeStatus, Optional[SiwoSecurityCodeHiddenInfo]
]


async def siwo_check_security_code(
    redis: redis.asyncio.client.Redis,
    email: Union[str, bytes],
    code: Union[str, bytes],
    now: float,
) -> Optional[SiwoCheckSecurityCodeResult]:
    """Checks if the given security code is a valid one sent to the given
    email address. The code is marked used if it was valid, ensuring this
    only returns true once per code.

    Args:
        redis (redis.asyncio.client.Redis): The redis client
        email (str, bytes): The email address the code was supposedly sent to
        code (str, bytes): The code to check
        now (float): The current time in seconds since the epoch, used for comparison
            with the codes expiration time. We store codes for longer than they are
            valid to help differentiate scanning attacks from users being really slow

    Returns:
        (str, SiwoSecurityCodeHiddenInfo or None), None: The parsed result. None
            if executed within a transaction, since the result is not known
            until the transaction is executed.

    Raises:
        NoScriptError: If the script is not loaded into redis
    """
    res = await redis.evalsha(  # type: ignore
        SIWO_CHECK_SECURITY_CODE_LUA_SCRIPT_HASH, 0, email, code, now  # type: ignore
    )
    if res is redis:
        return None
    return parse_siwo_check_security_code_result(res)


def parse_siwo_check_security_code_result(res) -> SiwoCheckSecurityCodeResult:
    """Parses the result of `siwo_check_security_code` into a more usable
    format. Only needs to be used when performing the operation within a
    transaction, as otherwise the result is parsed automatically.
    """
    assert isinstance(res, list), res
    assert len(res) == 2, res
    assert isinstance(res[0], int), res

    if res[0] < 0:
        assert res[1] is None
        return {
            -1: ("unknown", None),
            -2: ("lost", None),
            -3: ("bogus", None),
            -4: ("already_used", None),
            -5: ("expired", None),
            -6: ("revoked", None),
            -7: ("not_sent_yet", None),
        }[res[0]]

    assert res[0] == 1, res
    assert isinstance(res[1], list), res
    assert len(res[1]) == 4, res
    assert all(isinstance(x, (str, bytes)) for x in res[1]), res

    acknowledged_at_raw, delayed_raw, sent_at_raw, reason_raw = res[1]
    reason_str = (
        str(reason_raw, "utf-8")
        if isinstance(reason_raw, (bytes, memoryview, bytearray))
        else reason_raw
    )
    return (
        "valid",
        SiwoSecurityCodeHiddenInfo(
            acknowledged_at=float(acknowledged_at_raw),
            delayed=bool(int(delayed_raw)),
            sent_at=float(sent_at_raw),
            reason=typing_cast(SiwoSecurityCodeHiddenInfoReason, reason_str),
        ),
    )
