import secrets
import time
from typing import Optional, cast
from pydantic import BaseModel, Field
from fastapi import APIRouter, Response
from itgs import Itgs
import oauth.silent.lib.challenges
import oauth.silent.lib.core
import oauth.lib.exchange
import base64
from loguru import logger
import hashlib

router = APIRouter()


class CompleteChallengeLoginRequest(BaseModel):
    challenge_id: str = Field(
        description="The challenge id that was supplied to verify the challenge."
    )
    response_b64url: str = Field(
        description="The decrypted challenge, base64url encoded"
    )
    refresh_token_desired: bool = Field(
        False,
        description="If true, we may provide a refresh token in the response",
    )


class CompleteChallengeLoginResponse(BaseModel):
    id_token: str = Field(description="An id token for the Oseh user")
    refresh_token: Optional[str] = Field(
        description="A refresh token for the Oseh user, if desired and "
        "we are willing to porovide one"
    )


def _debug_print(name: str, value: bytes):
    sha1 = hashlib.sha1(value).hexdigest()
    logger.info(f"{name} ({len(value)} bytes) sha1: {sha1}")


@router.post(
    "/login",
    response_model=CompleteChallengeLoginResponse,
    responses={"400": {"description": "The challenge is not valid"}},
)
async def login_with_silentauth(args: CompleteChallengeLoginRequest):
    """Creates a silent auth identity with the corresponding public key if it
    does not exist. Then creates an Oseh user corresponding to that identity,
    if it does not exist. Finally, returns the id token and potentially a
    refresh token for the Oseh user.
    """
    async with Itgs() as itgs:
        logger.debug("processing login silent auth request")
        try:
            challenge_id = args.challenge_id.encode("ascii", errors="strict")
            response_bytes = base64.urlsafe_b64decode(
                args.response_b64url.encode("ascii", errors="strict") + b"=="
            )
        except Exception:
            logger.warning("failed to decode challenge or response")
            return Response(status_code=400)

        challenge = await oauth.silent.lib.challenges.retrieve_and_revoke_challenge(
            itgs, challenge_id=challenge_id
        )
        if challenge is None:
            logger.warning("failed to retrieve challenge")
            return Response(status_code=400)

        if not oauth.silent.lib.core.verify_silentauth_challenge(
            challenge, response_bytes
        ):
            logger.warning(f"failed to verify challenge")
            _debug_print("response_bytes", response_bytes)
            _debug_print("challenge.secret", challenge.secret)
            return Response(status_code=400)

        conn = await itgs.conn()
        cursor = conn.cursor()

        public_key_b64url = base64.urlsafe_b64encode(challenge.public_key).decode(
            "ascii"
        )
        response = await cursor.executeunified3(
            (
                (
                    """
INSERT INTO silentauth_accounts (
    uid, public_key, created_at
)
SELECT
    ?, ?, ?
WHERE
    NOT EXISTS (
        SELECT 1 FROM silentauth_accounts AS saa 
        WHERE saa.public_key = ?
    )
                    """,
                    (
                        f"oseh_saa_{secrets.token_urlsafe(64)}",
                        public_key_b64url,
                        time.time(),
                        public_key_b64url,
                    ),
                ),
                (
                    "SELECT uid FROM silentauth_accounts WHERE public_key = ?",
                    (public_key_b64url,),
                ),
            )
        )

        assert response[1].results, response
        saa_uid = cast(str, response[1].results[0][0])
        interpreted_claims = oauth.lib.exchange.InterpretedClaims(
            sub=saa_uid,
            email=None,
            email_verified=None,
            name=None,
            given_name=None,
            family_name=None,
            phone_number=None,
            phone_number_verified=None,
            picture=None,
            iat=int(time.time()),
        )

        user = await oauth.lib.exchange.initialize_user_from_info(
            itgs, "Silent", interpreted_claims, None
        )
        tokens = await oauth.lib.exchange.create_tokens_for_user(
            itgs,
            user=user,
            interpreted_claims=interpreted_claims,
            redirect_uri="",
            refresh_token_desired=args.refresh_token_desired,
        )
        return Response(
            content=CompleteChallengeLoginResponse.__pydantic_serializer__.to_json(
                CompleteChallengeLoginResponse(
                    id_token=tokens.id_token,
                    refresh_token=tokens.refresh_token,
                )
            ),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
