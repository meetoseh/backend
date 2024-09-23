import json
from fastapi import APIRouter, Response
from oauth.passkeys.lib.server import FIDO2_SERVERS
import fido2.webauthn
from itgs import Itgs
import oauth.passkeys.lib.challenges
from visitors.lib.get_or_create_visitor import VisitorSource
import base64

router = APIRouter()


@router.post("/authenticate_begin")
async def passkey_authenticate_begin(platform: VisitorSource, version: int):
    """Returns the configuration options for authenticating a registered passkey, webauthn
    style. You finish with either authenticate_merge_complete or authenticate_login_complete
    based on if you want a merge_token or an id_token
    """
    async with Itgs() as itgs:
        challenge = oauth.passkeys.lib.challenges.generate_challenge()
        options, state = FIDO2_SERVERS[platform].authenticate_begin(
            user_verification=fido2.webauthn.UserVerificationRequirement.DISCOURAGED,
            challenge=challenge,
        )
        await oauth.passkeys.lib.challenges.store_challenge_state(
            itgs,
            challenge=challenge,
            state=json.dumps(state).encode("utf8"),
            type=b"authenticate",
        )
        return Response(
            content=json.dumps(
                {
                    "challenge": base64.urlsafe_b64encode(challenge).decode("ascii"),
                    "rpId": options.public_key.rp_id,
                    "userVerification": "discouraged",
                }
            ),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=200,
        )
