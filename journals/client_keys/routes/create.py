import secrets
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Annotated, Optional, Literal
from auth import auth_any
from models import (
    AUTHORIZATION_UNKNOWN_TOKEN,
    STANDARD_ERRORS_BY_CODE,
    StandardErrorResponse,
)
from itgs import Itgs
from visitors.lib.get_or_create_visitor import (
    get_or_create_unsanitized_visitor,
)
import lib.journals.client_keys

from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
import base64

router = APIRouter()

# SECURITY:
#  Implementing RSA encryption only clientside is still pretty complicated so I've omitted it
#  for now, but it means in theory an active man-in-the-middle attack which inspects and alters
#  all journal client key requests could be used to compromise journal entries without causing
#  any unexpected requests to the backend, which is not desirable. However, due to the effort this
#  would take by the mitm, it's currently low priority.


class CreateJournalClientKeyRequest(BaseModel):
    platform: Literal["ios", "android", "browser"] = Field(
        description="The platform that the client is running on"
    )
    client_dh_public_key: str = Field(
        description=(
            "The client-side chosen public key for a diffie-hellman key exchange "
            "(group 14, https://www.ietf.org/rfc/rfc3526.txt), base64 (standard) encoded"
            # ". If `pinned_public_key` is provided, this must be encrypted using the indicated public key"
        )
    )
    # pinned_public_key: Optional[Literal["rsa-4096:2024-08"]] = Field(
    #     description=(
    #         "The identifier for the public key that was used to encrypt `client_dh_public_key`.\n\n"
    #         "The valid options are:\n"
    #         "- `rsa-4096:2024-08`: pad with OAEP (from PKCS#1 v2, RFC 2437, blank label, MGF1), use e=65537, n=<some public key here>"
    #     )
    # )


class CreateJournalClientKeyResponse(BaseModel):
    uid: str = Field(
        description="The UID that will be used to identify this key in the future"
    )
    server_dh_public_key: str = Field(
        description=(
            "The server-side chosen public key for a diffie-hellman key exchange "
            "(group 14, https://www.ietf.org/rfc/rfc3526.txt), base 64 (standard) encoded. "
            "After completing the diffie-hellman exchange, use the result as the IKM for "
            "HKDF-SHA256 to derive the final Fernet key."
        )
    )
    salt: str = Field(
        description=(
            "The salt that should be used in the HKDF-SHA256 derivation of the final Fernet key. "
            "base64 (standard) encoded."
        )
    )
    visitor: str = Field(
        description="The visitor value that should be used in future requests"
    )


# encodes GROUP_14_PRIME and GROUP_14_GENERATOR as PEM parameters
GROUP_14_PARAMETERS = b"""
-----BEGIN DH PARAMETERS-----
MIIBCAKCAQEA///////////JD9qiIWjCNMTGYouA3BzRKQJOCIpnzHQCC76mOxOb
IlFKCHmONATd75UZs806QxswKwpt8l8UN0/hNW1tUcJF5IW1dmJefsb0TELppjft
awv/XLb0Brft7jhr+1qJn6WunyQRfEsf5kkoZlHs5Fs9wgB8uKFjvwWY2kg2HFXT
mmkWP6j9JM9fg2VdI9yjrZYcYvNWIIVSu57VKQdwlpZtZww1Tkq8mATxdGwIyhgh
fDKQXkYuNs474553LBgOhgObJ4Oi7Aeij7XFXfBvTFLJ3ivL9pVYFxg5lUl86pVq
5RXSJhiY+gUQFXKOWoqsqmj//////////wIBAg==
-----END DH PARAMETERS-----
"""

GROUP_14_PRIME = int(
    """
FFFFFFFF FFFFFFFF C90FDAA2 2168C234 C4C6628B 80DC1CD1
29024E08 8A67CC74 020BBEA6 3B139B22 514A0879 8E3404DD
EF9519B3 CD3A431B 302B0A6D F25F1437 4FE1356D 6D51C245
E485B576 625E7EC6 F44C42E9 A637ED6B 0BFF5CB6 F406B7ED
EE386BFB 5A899FA5 AE9F2411 7C4B1FE6 49286651 ECE45B3D
C2007CB8 A163BF05 98DA4836 1C55D39A 69163FA8 FD24CF5F
83655D23 DCA3AD96 1C62F356 208552BB 9ED52907 7096966D
670C354E 4ABC9804 F1746C08 CA18217C 32905E46 2E36CE3B
E39E772C 180E8603 9B2783A2 EC07A28F B5C55DF0 6F4C52C9
DE2BCBF6 95581718 3995497C EA956AE5 15D22618 98FA0510
15728E5A 8AACAA68 FFFFFFFF FFFFFFFF
""".replace(
        " ", ""
    ).replace(
        "\n", ""
    ),
    16,
)
GROUP_14_GENERATOR = 2


ERROR_429_TYPES = Literal["ratelimited"]


@router.post(
    "/",
    response_model=CreateJournalClientKeyResponse,
    responses={
        "429": {
            "description": "Rate limited - try again later",
            "model": StandardErrorResponse[ERROR_429_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def create_journal_client_key(
    args: CreateJournalClientKeyRequest,
    authorization: Annotated[Optional[str], Header()] = None,
    visitor: Annotated[Optional[str], Header()] = None,
):
    """Creates a new Fernet symmetric key that can be used as an additional layer
    beyond TLS when Oseh communicates journal entries with the client. Although
    this would appear useless since its sent over TLS, this can be done at
    different (and fewer) times than journal entries themselves.

    An attacker would need to compromise TLS to see this request, then
    compromise this diffie-hellman 2048 bit group 14 exchange, then compromise
    TLS when the journal entry is transferred to read the journal entries, thus
    making this a reasonable defense in depth approach, especially when the key
    transfers are rare and attackers are expected to be at worst passive
    listeners that control a root certificate authority (so they wouldn't use
    the bearer token to make requests themselves, and they wouldn't emulate our
    servers beyond MITM due to the custom effort involved).

    Requires standard authorization.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        redis = await itgs.redis()
        result = await redis.set(
            f"journals:client_keys:ratelimits:created:user:{auth_result.result.sub}".encode(
                "utf-8"
            ),
            "1",
            ex=60,
            nx=True,
        )
        if not result:
            return Response(
                content=StandardErrorResponse[ERROR_429_TYPES](
                    type="ratelimited",
                    message="You have created too many keys recently. Please try again later.",
                ).model_dump_json(),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Retry-After": "60",
                },
                status_code=429,
            )

        now = time.time()
        visitor = await get_or_create_unsanitized_visitor(
            itgs, visitor=visitor, source=args.platform, seen_at=now
        )

        our_private_key = secrets.token_bytes(256)
        our_private_key_number = int.from_bytes(our_private_key, "big")
        our_public_key = powmod(
            GROUP_14_GENERATOR, our_private_key_number, GROUP_14_PRIME
        )
        our_public_key_bytes = our_public_key.to_bytes(256, "big")
        our_public_key_base64 = base64.b64encode(our_public_key_bytes).decode("ascii")

        peer_public_key_bytes = base64.b64decode(args.client_dh_public_key)
        peer_public_key_number = int.from_bytes(peer_public_key_bytes, "big")

        initial_key_material_number = powmod(
            peer_public_key_number, our_private_key_number, GROUP_14_PRIME
        )
        initial_key_material = initial_key_material_number.to_bytes(256, "big")

        salt = secrets.token_bytes(32)
        hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=None)
        fernet_key_material = hkdf.derive(initial_key_material)
        fernet_key = base64.urlsafe_b64encode(fernet_key_material)

        print(f"derived fernet key: {fernet_key}")

        new_key_result = await lib.journals.client_keys.create_journal_client_key(
            itgs,
            user_sub=auth_result.result.sub,
            platform=args.platform,
            visitor=visitor,
            now=now,
            new_key_data=fernet_key,
        )

        if new_key_result.type == "user_not_found":
            return AUTHORIZATION_UNKNOWN_TOKEN

        if new_key_result.type != "success":
            slack = await itgs.slack()
            await slack.send_web_error_message(
                f"Failed to create a new journal client key:\n\n```\n{new_key_result=}\n```",
                preview="Failed to create a new journal client key",
            )
            return Response(status_code=503, headers={"Retry-After": "180"})

        return Response(
            status_code=200,
            content=CreateJournalClientKeyResponse(
                uid=new_key_result.journal_client_key_uid,
                server_dh_public_key=our_public_key_base64,
                salt=base64.b64encode(salt).decode("ascii"),
                visitor=visitor,
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )


def powmod(base: int, secret: int, prime: int) -> int:
    """Computes (base ** secret) % prime"""
    x = base
    y = secret
    p = prime
    res = 1

    while y > 0:
        if y & 1:
            res = (res * x) % p
        y = y >> 1
        x = (x * x) % p

    return res
