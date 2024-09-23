import secrets
from typing import Literal, Optional
from itgs import Itgs
import base64


def generate_challenge() -> bytes:
    """Generates a challenge for creating or requesting a passkey. Needs to be stored
    with `store_challenge_state`
    """
    return secrets.token_bytes(32)


async def store_challenge_state(
    itgs: Itgs,
    /,
    *,
    challenge: bytes,
    state: bytes,
    type: Literal[b"register", b"authenticate"],
) -> None:
    """Stores the state associated with a challenge. This state is used to
    verify that the challenge is valid when it is returned to us.
    """
    redis = await itgs.redis()
    await redis.set(
        b"passkeys:challenges:" + type + b":" + base64.urlsafe_b64encode(challenge),
        state,
        ex=600,
    )


async def check_and_revoke_challenge(
    itgs: Itgs, /, *, challenge: bytes, type: Literal[b"register", b"authenticate"]
) -> Optional[bytes]:
    """Checks if a challenge identifier is valid. If it is, returns the corresponding
    state to validate. Otherwise, returns None.
    """
    key = b"passkeys:challenges:" + type + b":" + base64.urlsafe_b64encode(challenge)
    redis = await itgs.redis()
    async with redis.pipeline() as pipe:
        pipe.multi()
        await pipe.get(key)
        await pipe.delete(key)
        result, _ = await pipe.execute()
    return result
