import json
from fastapi import APIRouter, Response
from oauth.passkeys.lib.fido2_jsonify import credential_creation_options_to_client
from oauth.passkeys.lib.server import FIDO2_SERVERS
import fido2.webauthn
import secrets
from itgs import Itgs
import oauth.passkeys.lib.challenges
from visitors.lib.get_or_create_visitor import VisitorSource

router = APIRouter()


@router.post("/register_begin")
async def passkey_register_begin(platform: VisitorSource, version: int):
    """Returns the configuration options for registering a new passkey, webauthn
    style.
    """
    async with Itgs() as itgs:
        challenge = oauth.passkeys.lib.challenges.generate_challenge()
        options, state = FIDO2_SERVERS[platform].register_begin(
            user=fido2.webauthn.PublicKeyCredentialUserEntity(
                name="Oseh",
                id=secrets.token_urlsafe(32).encode("ascii"),
                display_name="Oseh",
            ),
            resident_key_requirement=fido2.webauthn.ResidentKeyRequirement.REQUIRED,
            user_verification=fido2.webauthn.UserVerificationRequirement.DISCOURAGED,
            authenticator_attachment=fido2.webauthn.AuthenticatorAttachment.PLATFORM,
            challenge=challenge,
        )
        await oauth.passkeys.lib.challenges.store_challenge_state(
            itgs,
            challenge=challenge,
            state=json.dumps(state).encode("utf8"),
            type=b"register",
        )
        prepared_options = credential_creation_options_to_client(options.public_key)
        print(f"{prepared_options=}")
        return Response(
            content=json.dumps(prepared_options).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=200,
        )
