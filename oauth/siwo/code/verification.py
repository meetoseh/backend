"""Module for working with email verification codes, i.e., codes requested using
a sign in with oseh JWT
"""
from itgs import Itgs


async def verify_and_revoke_code(itgs: Itgs, *, identity_uid: str, code: str) -> bool:
    """Verifies that we recently sent the sign in with oseh identity with the given
    uid the given code, and revokes the code if it is valid. This does not handle
    ratelimiting.

    Args:
        itgs (Itgs): the integrations to (re)use
        identity_uid (str): the uid of the identity who is using the code
        code (str): the verification code they provided

    Returns:
        bool: True if the code was valid and has been revoked, false if the code
            was not valid (or has already been revoked)
    """
    redis = await itgs.redis()
    result = await redis.zrem(
        f"sign_in_with_oseh:verification_codes_for_identity:{identity_uid}".encode(
            "utf-8"
        ),
        code.encode("utf-8"),
    )
    assert isinstance(result, int)
    return result == 1
