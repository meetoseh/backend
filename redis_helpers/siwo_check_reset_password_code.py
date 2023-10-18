from typing import Literal, Optional, List, Union
import hashlib
import time
import redis.asyncio.client
from dataclasses import dataclass

SIWO_CHECK_RESET_PASSWORD_CODE_LUA_SCRIPT = """
local code = ARGV[1]
local key = "sign_in_with_oseh:reset_password_codes:" .. code

local info = redis.call("HMGET", key, "used", "identity_uid", "sent_at")
local used = info[1]
if used == false then return {-1, false} end
if used ~= "0" then return {-2, false} end

local identity_uid = info[2]
local sent_at = tonumber(info[3])

redis.call("HSET", key, "used", "1")
redis.call("EXPIREAT", key, math.ceil(sent_at + 60 * 30))
return {1, identity_uid}
"""

SIWO_CHECK_RESET_PASSWORD_CODE_LUA_SCRIPT_HASH = hashlib.sha1(
    SIWO_CHECK_RESET_PASSWORD_CODE_LUA_SCRIPT.encode("utf-8")
).hexdigest()


_last_siwo_check_reset_password_code_ensured_at: Optional[float] = None


async def ensure_siwo_check_reset_password_code_script_exists(
    redis: redis.asyncio.client.Redis, *, force: bool = False
) -> None:
    """Ensures the siwo_check_reset_password_code lua script is loaded into redis."""
    global _last_siwo_check_reset_password_code_ensured_at

    now = time.time()
    if (
        not force
        and _last_siwo_check_reset_password_code_ensured_at is not None
        and (now - _last_siwo_check_reset_password_code_ensured_at < 5)
    ):
        return

    loaded: List[bool] = await redis.script_exists(
        SIWO_CHECK_RESET_PASSWORD_CODE_LUA_SCRIPT_HASH
    )
    if not loaded[0]:
        correct_hash = await redis.script_load(
            SIWO_CHECK_RESET_PASSWORD_CODE_LUA_SCRIPT
        )
        assert (
            correct_hash == SIWO_CHECK_RESET_PASSWORD_CODE_LUA_SCRIPT_HASH
        ), f"{correct_hash=} != {SIWO_CHECK_RESET_PASSWORD_CODE_LUA_SCRIPT_HASH=}"

    if (
        _last_siwo_check_reset_password_code_ensured_at is None
        or _last_siwo_check_reset_password_code_ensured_at < now
    ):
        _last_siwo_check_reset_password_code_ensured_at = now


@dataclass
class SiwoCheckResetPasswordCodeError:
    category: Literal["used", "dne"]
    """The category of error that occurred."""


@dataclass
class SiwoCheckResetPasswordCodeResult:
    error: Optional[SiwoCheckResetPasswordCodeError]
    identity_uid: Optional[str]

    @property
    def valid(self) -> bool:
        return self.identity_uid is not None


async def siwo_check_reset_password_code(
    redis: redis.asyncio.client.Redis, code: Union[str, bytes]
) -> Optional[SiwoCheckResetPasswordCodeResult]:
    """Checks if the given reset password code is valid

    Args:
        redis (redis.asyncio.client.Redis): The redis client
        code (str, bytes): the reset password code to check

    Returns:
        SiwoCheckResetPasswordCodeResult, None: The result. None if executed
            within a transaction, since the result is not known until the
            transaction is executed.

    Raises:
        NoScriptError: If the script is not loaded into redis
    """
    res = await redis.evalsha(SIWO_CHECK_RESET_PASSWORD_CODE_LUA_SCRIPT_HASH, 0, code)
    if res is redis:
        return None
    return parse_siwo_check_reset_password_code(res)


def parse_siwo_check_reset_password_code(res) -> SiwoCheckResetPasswordCodeResult:
    """Parses the result of the script. Generally only has to be called directly
    if executing the script within a transaction
    """
    assert isinstance(res, (tuple, list)), res
    assert len(res) == 2, res
    assert isinstance(res[0], int), res

    if res[0] == 1:
        if isinstance(res[1], str):
            return SiwoCheckResetPasswordCodeResult(error=None, identity_uid=res[1])
        if isinstance(res[1], bytes):
            return SiwoCheckResetPasswordCodeResult(
                error=None, identity_uid=res[1].decode("utf-8")
            )
        assert False, res

    if res[0] == -1:
        return SiwoCheckResetPasswordCodeResult(
            error=SiwoCheckResetPasswordCodeError(category="used"),
            identity_uid=None,
        )

    if res[0] == -2:
        return SiwoCheckResetPasswordCodeResult(
            error=SiwoCheckResetPasswordCodeError(category="dne"),
            identity_uid=None,
        )

    assert False, res
