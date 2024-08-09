import hashlib
import hmac
from typing import Annotated, Literal, Optional
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from error_middleware import handle_warning
from itgs import Itgs
from lib.journals.client_keys import get_journal_client_key
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from auth import auth_any


router = APIRouter()


class TestJournalClientKeyRequest(BaseModel):
    journal_client_key_uid: str = Field(
        description="the UID identifying which journal client key to use to encrypt the response from the system"
    )
    encrypted_payload: str = Field(
        description="the encrypted payload to be decrypted with the journal client key"
    )
    expected_sha256: str = Field(
        description="the expected SHA256 hash (hex-encoded) of the decrypted payload; there is already a signature on the "
        "fernet key, but since you are trying to test the encryption algorithm itself its helpful to have "
        "a second simpler check"
    )


ERROR_400_TYPES = Literal["bad_payload"]
ERROR_404_TYPES = Literal["key_unavailable"]
ERROR_409_TYPES = Literal["mismatch"]
ERROR_429_TYPES = Literal["ratelimited"]


@router.post(
    "/test",
    status_code=200,
    responses={
        **STANDARD_ERRORS_BY_CODE,
        "400": {
            "description": "The provided payload could not be decrypted",
            "model": StandardErrorResponse[ERROR_400_TYPES],
        },
        "404": {
            "description": "The provided journal client key is not available or is not acceptable for this transfer. Generate a new one.",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        "409": {
            "description": "The provided payload does not match the expected SHA256 hash",
            "model": StandardErrorResponse[ERROR_409_TYPES],
        },
        "429": {
            "description": "You have been rate limited. Please try again later.",
            "model": StandardErrorResponse[ERROR_429_TYPES],
        },
    },
)
async def test_journal_client_key(
    args: TestJournalClientKeyRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Tests that we can decrypt the given payload to match the given sha256 hash.
    This is useful for verifying the client implementation of the encryption algorithm.

    Requires standard authorization for the same user that the indicated journal client
    key belongs to.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        client_key = await get_journal_client_key(
            itgs,
            user_sub=auth_result.result.sub,
            journal_client_key_uid=args.journal_client_key_uid,
            read_consistency="none",
        )
        if client_key.type == "not_found":
            client_key = await get_journal_client_key(
                itgs,
                user_sub=auth_result.result.sub,
                journal_client_key_uid=args.journal_client_key_uid,
                read_consistency="weak",
            )

        if client_key.type != "success":
            await handle_warning(
                f"{__name__}:missing_journal_client_key",
                f"User {auth_result.result.sub} tried to test a journal client key, but we "
                f"could not retrieve it: {client_key.type}",
            )
            return Response(
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="key_unavailable",
                    message="The provided journal client key is not available or is not acceptable for this transfer. Generate a new one.",
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=404,
            )

        try:
            decrypted_payload = client_key.journal_client_key.decrypt(
                args.encrypted_payload, ttl=120
            )
        except Exception as e:
            await handle_warning(
                f"{__name__}:decryption_failure",
                f"User {auth_result.result.sub} tried to test a journal client key, but we "
                f"could not decrypt the payload: {e}",
            )
            return Response(
                content=StandardErrorResponse[ERROR_400_TYPES](
                    type="bad_payload",
                    message="The provided payload could not be decrypted",
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=400,
            )

        decrypted_sha256 = hashlib.sha256(decrypted_payload).hexdigest()
        if not hmac.compare_digest(decrypted_sha256, args.expected_sha256):
            await handle_warning(
                f"{__name__}:mismatched_sha256",
                f"User {auth_result.result.sub} tried to test a journal client key, but the decrypted "
                f"payload did not match the expected SHA256 hash",
            )
            return Response(
                content=StandardErrorResponse[ERROR_409_TYPES](
                    type="mismatch",
                    message="The provided payload does not match the expected SHA256 hash",
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=409,
            )

        return Response(status_code=200)
