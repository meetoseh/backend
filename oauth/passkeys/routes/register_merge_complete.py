import json
import secrets
import time
from typing import Annotated, Optional
from fastapi import APIRouter, Header, Response
from pydantic import BaseModel, Field
from error_middleware import handle_warning
from oauth.passkeys.lib.server import FIDO2_SERVERS
import fido2.webauthn
from itgs import Itgs
import oauth.passkeys.lib.challenges
from oauth.passkeys.routes.authenticate_merge_complete import (
    OauthPasskeyAuthenticateMergeCompleteResponse,
)
import base64
from auth import auth_any
import oauth.lib.exchange
import oauth.lib.merging.start_merge_auth
from visitors.lib.get_or_create_visitor import VisitorSource

router = APIRouter()


class OauthPasskeyRegisterMergeCompleteRequest(BaseModel):
    id_b64url: str = Field(description="The id from the response, base64url encoded")
    client_data_json_b64url: str = Field(
        description="The clientDataJSON from the response as bytes, base64url encoded"
    )
    attestation_object_b64url: str = Field(
        description="The attestationObject from the response as bytes, base64url encoded"
    )


@router.post(
    "/register_merge_complete",
    response_model=OauthPasskeyAuthenticateMergeCompleteResponse,
)
async def passkey_register_merge_complete(
    args: OauthPasskeyRegisterMergeCompleteRequest,
    platform: VisitorSource,
    version: int,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Completes the registration of a new passkey identity and returns a merge token
    that can be used to associate the new passkey identity with the authorized
    user from the authorization header.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization=authorization)
        if auth_result.result is None:
            return auth_result.error_response

        response = fido2.webauthn.RegistrationResponse(
            id=base64.urlsafe_b64decode(args.id_b64url + "=="),
            response=fido2.webauthn.AuthenticatorAttestationResponse(
                client_data=fido2.webauthn.CollectedClientData(
                    base64.urlsafe_b64decode(args.client_data_json_b64url + "==")
                ),
                attestation_object=fido2.webauthn.AttestationObject(
                    base64.urlsafe_b64decode(args.attestation_object_b64url + "==")
                ),
            ),
            authenticator_attachment=None,
        )
        state = await oauth.passkeys.lib.challenges.check_and_revoke_challenge(
            itgs, challenge=response.response.client_data.challenge, type=b"register"
        )
        if state is None:
            return Response(status_code=404)
        parsed_state = json.loads(state)
        credential = FIDO2_SERVERS[platform].register_complete(parsed_state, response)
        assert credential.credential_data is not None, credential

        conn = await itgs.conn()
        cursor = conn.cursor("weak")

        new_uid = f"oseh_pka_{secrets.token_urlsafe(64)}"

        credential_b64url = base64.urlsafe_b64encode(credential).decode("ascii")
        now = time.time()
        response = await cursor.execute(
            """
INSERT INTO passkey_accounts (
    uid,
    client_id,
    credential,
    created_at
)
SELECT ?, ?, ?, ?
WHERE
    NOT EXISTS (
        SELECT 1 FROM passkey_accounts
        WHERE passkey_accounts.client_id = ?
    )
            """,
            (
                new_uid,
                args.id_b64url,
                credential_b64url,
                now,
                args.id_b64url,
            ),
        )
        if response.rows_affected is None or response.rows_affected < 1:
            await handle_warning(
                f"{__name__}:duplicate_credential",
                f"Attempted to register duplicate client id: `{args.id_b64url}`",
            )
            return Response(status_code=409)

        interpreted_claims = oauth.lib.exchange.InterpretedClaims(
            sub=new_uid,
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
            provider="Passkey",
            provider_claims=interpreted_claims.model_dump(),
        )
        return Response(
            content=OauthPasskeyAuthenticateMergeCompleteResponse.__pydantic_serializer__.to_json(
                OauthPasskeyAuthenticateMergeCompleteResponse(merge_token=merge_jwt)
            ),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
