import json
import secrets
import time
from fastapi import APIRouter, Response
from pydantic import BaseModel, Field
from error_middleware import handle_warning
from oauth.passkeys.lib.server import FIDO2_SERVERS
import fido2.webauthn
from itgs import Itgs
import oauth.passkeys.lib.challenges
from oauth.passkeys.routes.authenticate_login_complete import (
    OauthPasskeyAuthenticateLoginCompleteResponse,
)
import base64
import oauth.lib.exchange
from visitors.lib.get_or_create_visitor import VisitorSource

router = APIRouter()


class OauthPasskeyRegisterCompleteRequest(BaseModel):
    id_b64url: str = Field(description="The id from the response, base64url encoded")
    client_data_json_b64url: str = Field(
        description="The clientDataJSON from the response as bytes, base64url encoded"
    )
    attestation_object_b64url: str = Field(
        description="The attestationObject from the response as bytes, base64url encoded"
    )
    refresh_token_desired: bool = Field(
        False,
        description="If true, we may provide a refresh token in the response",
    )


@router.post(
    "/register_login_complete",
    response_model=OauthPasskeyAuthenticateLoginCompleteResponse,
)
async def passkey_register_login_complete(
    args: OauthPasskeyRegisterCompleteRequest, platform: VisitorSource, version: int
):
    """Completes the registration of a new passkey identity. Then, creates a new Oseh user
    and attaches the passkey identity to it. Finally, returns the id token (and optionally a
    refresh token) for that Oseh user.
    """
    async with Itgs() as itgs:
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
        credential = FIDO2_SERVERS[platform].register_complete(
            json.loads(state), response
        )
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
        user = await oauth.lib.exchange.initialize_user_from_info(
            itgs, "Passkey", interpreted_claims, None
        )
        tokens = await oauth.lib.exchange.create_tokens_for_user(
            itgs,
            user=user,
            interpreted_claims=interpreted_claims,
            redirect_uri="",
            refresh_token_desired=args.refresh_token_desired,
        )
        return Response(
            content=OauthPasskeyAuthenticateLoginCompleteResponse.__pydantic_serializer__.to_json(
                OauthPasskeyAuthenticateLoginCompleteResponse(
                    id_token=tokens.id_token,
                    refresh_token=tokens.refresh_token,
                )
            ),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
