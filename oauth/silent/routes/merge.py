import secrets
import time
from typing import Annotated, Optional, cast
from pydantic import BaseModel, Field
from fastapi import APIRouter, Header
from fastapi.responses import Response
from itgs import Itgs
from models import STANDARD_ERRORS_BY_CODE
import oauth.silent.lib.challenges
import oauth.silent.lib.core
import oauth.lib.exchange
import oauth.lib.merging.start_merge_auth
import base64
from auth import auth_any

router = APIRouter()


class CompleteChallengeMergeRequest(BaseModel):
    challenge_id: str = Field(
        description="The challenge id that was supplied to verify the challenge."
    )
    response_b64url: str = Field(
        description="The decrypted challenge, base64url encoded"
    )


class CompleteChallengeMergeResponse(BaseModel):
    merge_token: str = Field(description="The merge token to use")


@router.post(
    "/merge",
    response_model=CompleteChallengeMergeResponse,
    responses={
        "400": {"description": "The challenge is not valid"},
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def merge_with_silentauth(
    args: CompleteChallengeMergeRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Creates a silent auth identity with the corresponding public key if it
    does not exist. Then returns the merge token for merging that identity into the
    authorized user from the Authorization header
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        try:
            challenge_id = args.challenge_id.encode("ascii", errors="strict")
            response_bytes = base64.urlsafe_b64decode(
                args.response_b64url.encode("ascii", errors="strict") + b"=="
            )
        except Exception:
            return Response(status_code=400)

        challenge = await oauth.silent.lib.challenges.retrieve_and_revoke_challenge(
            itgs, challenge_id=challenge_id
        )
        if challenge is None:
            return Response(status_code=400)

        if not oauth.silent.lib.core.verify_silentauth_challenge(
            challenge, response_bytes
        ):
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
        merge_jwt = await oauth.lib.merging.start_merge_auth.create_jwt(
            itgs,
            original_user_sub=auth_result.result.sub,
            provider="Silent",
            provider_claims=interpreted_claims.model_dump(),
        )
        return Response(
            content=CompleteChallengeMergeResponse.__pydantic_serializer__.to_json(
                CompleteChallengeMergeResponse(merge_token=merge_jwt)
            ),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
