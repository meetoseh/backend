import secrets
from typing import Literal, Optional
from itgs import Itgs
from dataclasses import dataclass


@dataclass
class RSA4096V1KeyChallengeRequest:
    type: Literal["rsa-4096-v1"]
    """
    - `rsa-4096-v1`: 4096 bit RSA key with 65537 as the public exponent
    """
    public_key: bytes
    """The 4096-bit / 512 byte public key"""


@dataclass
class RSA4096V1KeyChallenge:
    type: Literal["rsa-4096-v1"]
    public_key: bytes
    """The 512 byte public key that the client claims to have"""
    challenge_id: bytes
    """The identifier that can be sent to the client in plaintext to reference
    this challenge. Improves lookup performance as challenges are long.
    """
    secret: bytes
    """
    The 382 byte challenge that must be encrypted with their public key
    before sending it to them, which they will need to send back
    """


def generate_challenge(req: RSA4096V1KeyChallengeRequest) -> RSA4096V1KeyChallenge:
    """Generates a challenge identifier for registering or authenticating a silent
    key. Needs to be stored with `store_challenge`
    """
    assert req.type == "rsa-4096-v1", req
    assert len(req.public_key) == 512, len(req.public_key)

    challenge_id = secrets.token_urlsafe(32).encode("ascii")
    secret = secrets.token_bytes(382)
    return RSA4096V1KeyChallenge(
        type="rsa-4096-v1",
        public_key=req.public_key,
        challenge_id=challenge_id,
        secret=secret,
    )


async def store_challenge(itgs: Itgs, /, *, challenge: RSA4096V1KeyChallenge) -> None:
    """Stores the state associated with a challenge. To complete the challenge,
    the client must provide the public id (sent freely) and the challenge (sent
    encrypted with the indicated public key). The client has 60 seconds to complete
    the challenge before it is automatically revoked.
    """
    assert challenge.type == "rsa-4096-v1", challenge
    assert len(challenge.secret) == 382, len(challenge.secret)
    assert len(challenge.public_key) == 512, len(challenge.public_key)

    state = bytearray(895)
    state[0] = (1).to_bytes(1, "big")[0]
    state[1:383] = challenge.secret
    state[383:] = challenge.public_key

    redis = await itgs.redis()
    await redis.set(
        b"silentauth:challenges:" + challenge.challenge_id,
        memoryview(state),
        ex=60,
    )


async def retrieve_and_revoke_challenge(
    itgs: Itgs,
    /,
    *,
    challenge_id: bytes,
) -> Optional[RSA4096V1KeyChallenge]:
    """Returns and revokes the challenge with the given public id, if it
    exists.
    """
    key = b"silentauth:challenges:" + challenge_id
    redis = await itgs.redis()
    async with redis.pipeline() as pipe:
        pipe.multi()
        await pipe.get(key)
        await pipe.delete(key)
        result, _ = await pipe.execute()
    if result is None:
        return None

    assert isinstance(result, (bytes, memoryview, bytearray)), type(result)
    result = bytes(result) if not isinstance(result, bytes) else result
    type_byte = int.from_bytes(result[0:1], "big", signed=False)
    assert type_byte == 1, type_byte
    assert len(result) == 895, len(result)
    challenge_bytes = result[1:383]
    public_key = result[383:]
    return RSA4096V1KeyChallenge(
        type="rsa-4096-v1",
        public_key=public_key,
        challenge_id=challenge_id,
        secret=challenge_bytes,
    )
