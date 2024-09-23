from typing import Literal
from pydantic import BaseModel, Field
from fastapi import APIRouter, Response
from itgs import Itgs
from models import StandardErrorResponse
import oauth.silent.lib.challenges
import oauth.silent.lib.core
import base64
from loguru import logger
import hashlib

router = APIRouter()


class ChallengeRequest(BaseModel):
    type: Literal["rsa-4096-v1"] = Field(
        description="For future expansion; indicates you want to use a 4096 bit rsa key with 65337 as the public exponent."
    )
    public_key_b64url: str = Field(
        description="The 4096 bit RSA public modulus, base64url encoded."
    )


class EncryptedChallengeResponse(BaseModel):
    challenge_id: str = Field(
        description="The challenge id that must be supplied to verify the challenge."
    )
    challenge_b64url: str = Field(
        description="The challenge to decrypt, encrypted with the given public key, base64url encoded."
    )


ERROR_RATELIMITED_TYPES = Literal["ratelimited"]


@router.post(
    "/begin",
    response_model=EncryptedChallengeResponse,
    responses={
        "400": {"description": "The public key is not valid"},
        "429": {
            "description": "There are too many silent auth requests recently. Try again later.",
            "model": StandardErrorResponse[ERROR_RATELIMITED_TYPES],
        },
    },
)
async def silent_auth_begin(args: ChallengeRequest):
    """Produces a challenge to prove the client has the given public key, by encrypting
    a secret with the public key that the client must decrypt and return. The client has up
    to a minute to complete the process before the challenge is revoked.
    """
    async with Itgs() as itgs:
        logger.debug("processing begin silent auth request")
        try:
            public_key_bytes = base64.urlsafe_b64decode(args.public_key_b64url + "==")
        except Exception as e:
            logger.warning("failed to decode public key")
            return Response(status_code=400)

        if len(public_key_bytes) != 512:
            logger.warning(
                f"public key is not 512 bytes (it is {len(public_key_bytes)} bytes)"
            )
            return Response(status_code=400)

        public_key_hash = hashlib.sha1(public_key_bytes).digest()
        logger.debug("received public key sha1 hash: " + public_key_hash.hex())

        challenge = oauth.silent.lib.challenges.generate_challenge(
            oauth.silent.lib.challenges.RSA4096V1KeyChallengeRequest(
                type="rsa-4096-v1", public_key=public_key_bytes
            )
        )
        response_bytes = oauth.silent.lib.core.encrypt_silentauth_challenge(challenge)
        await oauth.silent.lib.challenges.store_challenge(itgs, challenge=challenge)
        logger.info(
            f"successfully generated challenge {challenge.challenge_id.decode('ascii')}"
        )
        return Response(
            content=EncryptedChallengeResponse.__pydantic_serializer__.to_json(
                EncryptedChallengeResponse(
                    challenge_id=challenge.challenge_id.decode("ascii"),
                    challenge_b64url=base64.urlsafe_b64encode(response_bytes).decode(
                        "ascii"
                    ),
                )
            ),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=200,
        )
