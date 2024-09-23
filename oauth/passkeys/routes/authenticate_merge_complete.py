import json
import time
from typing import Annotated, Optional, cast
from fastapi import APIRouter, Response, Header
from pydantic import BaseModel, Field
from oauth.passkeys.lib.server import FIDO2_SERVERS
import fido2.webauthn
from itgs import Itgs
import oauth.passkeys.lib.challenges
import oauth.lib.exchange
import oauth.lib.merging.start_merge_auth
import base64
from auth import auth_any
from visitors.lib.get_or_create_visitor import VisitorSource

router = APIRouter()


class OauthPasskeyAuthenticateMergeCompleteRequest(BaseModel):
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


class OauthPasskeyAuthenticateMergeCompleteResponse(BaseModel):
    merge_token: str = Field(
        description="A merge token for the Oseh user, to be used in the merge process"
    )


@router.post(
    "/authenticate_merge_complete",
    response_model=OauthPasskeyAuthenticateMergeCompleteResponse,
)
async def passkey_authenticate_merge_complete(
    args: OauthPasskeyAuthenticateMergeCompleteRequest,
    platform: VisitorSource,
    version: int,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Finishes the authentication process for a passkey, generating a merge
    token which merges the Passkey account from args into the user from
    authorization
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization=authorization)
        if auth_result.result is None:
            return auth_result.error_response

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
