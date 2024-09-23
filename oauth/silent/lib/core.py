from oauth.silent.lib.challenges import RSA4096V1KeyChallenge
import hashlib
import secrets
import hmac
from loguru import logger


LABEL_HASH = hashlib.sha512(b"").digest()


def encrypt_silentauth_challenge(challenge: RSA4096V1KeyChallenge) -> bytes:
    """
    Encrypts the challenge into the byte string that can be sent to the client. Specifically,
    the `challenge` within an rsa 4096 v1 key challenge is the corresponding challenge
    encrypted with the indicated public key.
    """
    assert challenge.type == "rsa-4096-v1", challenge
    assert len(challenge.secret) == 382, len(challenge.secret)
    assert len(challenge.public_key) == 512, len(challenge.public_key)

    logger.info(
        f"encrypting challenge sha1 {hashlib.sha1(challenge.secret).hexdigest()}"
    )
    padded_message = pad_oaep(challenge.secret)
    logger.info(f"padded message sha1 {hashlib.sha1(padded_message).hexdigest()}")
    message_as_int = int.from_bytes(padded_message, "big", signed=False)
    public_key_as_int = int.from_bytes(challenge.public_key, "big", signed=False)
    challenge_as_int = pow(message_as_int, 65537, public_key_as_int)
    challenge_bytes = challenge_as_int.to_bytes(512, "big", signed=False)
    logger.info(f"challenge bytes sha1 {hashlib.sha1(challenge_bytes).hexdigest()}")
    return challenge_bytes


def verify_silentauth_challenge(
    challenge: RSA4096V1KeyChallenge, response: bytes
) -> bool:
    """Verifies that the given response is the correct response to the challenge"""
    return hmac.compare_digest(challenge.secret, response)


def _debug_print(name: str, value: bytes):
    sha1 = hashlib.sha1(value).hexdigest()
    logger.info(f"{name} ({len(value)} bytes) sha1: {sha1}")


def pad_oaep(message: bytes) -> bytes:
    """Converts at most 382 bytes into the 512 byte OAEP padded message"""
    if len(message) > 382:
        raise ValueError(f"Message is too long: {len(message)} bytes > 382 bytes")

    padding_string = bytes(382 - len(message))

    data_block = LABEL_HASH + padding_string + b"\x01" + message
    seed = secrets.token_bytes(64)
    db_mask = mgf1(seed=seed, length=447)
    masked_db = xor(data_block, db_mask)
    seed_mask = mgf1(seed=masked_db, length=64)
    masked_seed = xor(seed, seed_mask)
    result = b"\x00" + masked_seed + masked_db

    _debug_print("padded", result)
    _debug_print("masked seed", masked_seed)
    _debug_print("masked db", masked_db)
    _debug_print("seed mask", seed_mask)
    _debug_print("seed", seed)
    _debug_print("db mask", db_mask)
    _debug_print("data block", data_block)
    _debug_print("message", message)

    return result


def xor(a: bytes, b: bytes) -> bytes:
    """XORs two byte strings"""
    return bytes(x ^ y for x, y in zip(a, b))


def mgf1(*, seed: bytes, length: int) -> bytes:
    """Mask generation function for OAEP"""
    if length >= 64 * (2**32):
        raise ValueError(f"{length} bytes is too large")

    result = b""
    counter = 0
    while True:
        C = counter.to_bytes(4, "big", signed=False)
        result += hashlib.sha512(seed + C).digest()
        counter += 1

        if len(result) >= length:
            return result[:length]
