import json
import time
from typing import Optional, cast
from fastapi import APIRouter, Response
from pydantic import BaseModel, Field
from oauth.passkeys.lib.server import FIDO2_SERVERS
import fido2.webauthn
from itgs import Itgs
import oauth.passkeys.lib.challenges
import oauth.lib.exchange
import base64

from visitors.lib.get_or_create_visitor import VisitorSource

router = APIRouter()


class OauthPasskeyAuthenticateLoginCompleteRequest(BaseModel):
    id_b64url: str = Field(description="The id from the response, base64url encoded")
    authenticator_data_b64url: str = Field(
        description="The authenticatorData from the response as bytes, base64url encoded"
    )
    client_data_json_b64url: str = Field(
        description="The clientDataJSON from the response as bytes, base64url encoded"
    )
    signature_b64url: str = Field(
        description="The signature from the response as bytes, base64url encoded"
    )
    refresh_token_desired: bool = Field(
        False,
        description="If true, we may provide a refresh token in the response",
    )


class OauthPasskeyAuthenticateLoginCompleteResponse(BaseModel):
    id_token: str = Field(description="An id token for the Oseh user")
    refresh_token: Optional[str] = Field(
        description="A refresh token for the Oseh user, if desired and "
        "we are willing to provide one"
    )


@router.post(
    "/authenticate_login_complete",
    response_model=OauthPasskeyAuthenticateLoginCompleteResponse,
)
async def passkey_authenticate_login_complete(
    args: OauthPasskeyAuthenticateLoginCompleteRequest,
    platform: VisitorSource,
    version: int,
):
    """Finishes the authentication process for a passkey, creating or logging into the
    corresponding Oseh user, returning the id token (and optionally a refresh token).
    """
    async with Itgs() as itgs:
        authentication_response = fido2.webauthn.AuthenticationResponse(
            id=base64.urlsafe_b64decode(args.id_b64url + "=="),
            response=fido2.webauthn.AuthenticatorAssertionResponse(
                client_data=fido2.webauthn.CollectedClientData(
                    base64.urlsafe_b64decode(args.client_data_json_b64url + "==")
                ),
                authenticator_data=fido2.webauthn.AuthenticatorData(
                    base64.urlsafe_b64decode(args.authenticator_data_b64url + "==")
                ),
                signature=base64.urlsafe_b64decode(args.signature_b64url + "=="),
            ),
            authenticator_attachment=None,
        )
        state = await oauth.passkeys.lib.challenges.check_and_revoke_challenge(
            itgs,
            challenge=authentication_response.response.client_data.challenge,
            type=b"authenticate",
        )
        if state is None:
            return Response(status_code=404)

        conn = await itgs.conn()
        cursor = conn.cursor("weak")

        response = await cursor.execute(
            "SELECT uid, credential FROM passkey_accounts WHERE client_id = ?",
            (args.id_b64url,),
        )

        if not response.results:
            return Response(status_code=404)

        pka_uid = cast(str, response.results[0][0])
        credential_b64url = cast(str, response.results[0][1])
        credential = fido2.webauthn.AuthenticatorData(
            base64.urlsafe_b64decode(credential_b64url)
        )
        assert credential.credential_data is not None, credential

        credential = FIDO2_SERVERS[platform].authenticate_complete(
            json.loads(state), [credential.credential_data], authentication_response
        )
        interpreted_claims = oauth.lib.exchange.InterpretedClaims(
            sub=pka_uid,
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
