from fastapi import APIRouter, Header, Response
from typing import Annotated, Literal, Optional, cast
from error_middleware import handle_warning
from lib.journals.client_keys import get_journal_client_key
from models import (
    STANDARD_ERRORS_BY_CODE,
    StandardErrorResponse,
    AUTHORIZATION_UNKNOWN_TOKEN,
)
from pydantic import BaseModel, Field, validator
import journals.entry_auth
import auth as std_auth
from itgs import Itgs
from visitors.lib.get_or_create_visitor import VisitorSource


router = APIRouter()


class ShowJournalMetadataRequest(BaseModel):
    platform: VisitorSource = Field(description="The platform the client is on")
    journal_entry_uid: str = Field(
        description="The UID of the journal entry whose metadata to fetch"
    )
    journal_entry_jwt: str = Field(
        description="The JWT which provides access to the journal entry"
    )
    journal_client_key_uid: str = Field(
        description="The journal client key to use as an additional layer of encryption for the response"
    )
    min_consistency: Literal["none", "weak"] = Field(
        "none",
        description=(
            "The minimum consistency that the client thinks is required. "
            "We may ratelimit higher values more aggressively."
        ),
    )


class ShowJournalMetadataResponsePayload(BaseModel):
    uid: str = Field(description="The UID of the journal entry")
    created_at: float = Field(
        description="When the journal entry was created in seconds since the epoch"
    )
    canonical_at: float = Field(
        description=(
            "The canonical timestamp that should be used if only one timestamp is "
            "being shown for the journal entry."
        )
    )


class ShowJournalMetadataResponse(BaseModel):
    encrypted_payload: str = Field(
        description="The journal entry metadata encrypted with the journal client key. The decrypted contents are a json object in the form indicated by `payload`"
    )
    payload: Optional[ShowJournalMetadataResponsePayload] = Field(
        None,
        description="Never set. Used to show what the contents of the encrypted payload are in the documentation",
    )

    @validator("payload", pre=True)
    def validate_payload_is_none(cls, v):
        if v is not None:
            raise ValueError("The payload field must be None")
        return v


ERROR_404_TYPES = Literal["journal_entry_not_found", "key_unavailable"]
ERROR_JOURNAL_ENTRY_NOT_FOUND_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="journal_entry_not_found",
        message="The indicated journal entry was not found despite valid authorization. It was deleted.",
    ).model_dump_json(),
    headers={
        "Content-Type": "application/json; charset=utf-8",
    },
    status_code=404,
)
ERROR_KEY_UNAVAILABLE_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="key_unavailable",
        message="The indicated journal client key was not found or is not acceptable for this request. Generate a new one.",
    ).model_dump_json(),
    headers={
        "Content-Type": "application/json; charset=utf-8",
    },
    status_code=404,
)


@router.post(
    "/show_metadata",
    response_model=ShowJournalMetadataResponse,
    responses={
        **STANDARD_ERRORS_BY_CODE,
        "404": {
            "description": "Either the journal entry has been deleted or the client key needs to be regenerated",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
    },
)
async def show_journal_entry_metadata(
    args: ShowJournalMetadataRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Retrieves metadata about the journal entry with the given uid, provided
    it belongs to the user, you have a valid JWT for it, and you use a journal
    client key for an additional layer of encryption.

    Requires standard authorization for the same user who owns the journal entry
    and the journal entry JWT was issued to.
    """
    async with Itgs() as itgs:
        std_auth_result = await std_auth.auth_any(itgs, authorization)
        if std_auth_result.result is None:
            return std_auth_result.error_response

        entry_auth_result = await journals.entry_auth.auth_any(
            itgs, f"bearer {args.journal_entry_jwt}"
        )
        if entry_auth_result.result is None:
            return entry_auth_result.error_response

        if std_auth_result.result.sub != entry_auth_result.result.user_sub:
            return AUTHORIZATION_UNKNOWN_TOKEN

        if entry_auth_result.result.journal_entry_uid != args.journal_entry_uid:
            return AUTHORIZATION_UNKNOWN_TOKEN

        if (
            entry_auth_result.result.journal_client_key_uid is not None
            and entry_auth_result.result.journal_client_key_uid
            != args.journal_client_key_uid
        ):
            return AUTHORIZATION_UNKNOWN_TOKEN

        journal_client_key = await get_journal_client_key(
            itgs,
            user_sub=std_auth_result.result.sub,
            journal_client_key_uid=args.journal_client_key_uid,
            read_consistency="none",
        )
        if journal_client_key.type == "not_found":
            journal_client_key = await get_journal_client_key(
                itgs,
                user_sub=std_auth_result.result.sub,
                journal_client_key_uid=args.journal_client_key_uid,
                read_consistency="weak",
            )

        if journal_client_key.type != "success":
            await handle_warning(
                f"{__name__}:client_key:{journal_client_key.type}",
                f"User `{std_auth_result.result.sub}` tried to access journal entry metadata with a journal client key that was not found or not acceptable for this request. The journal client key uid was `{args.journal_client_key_uid}`",
            )
            return ERROR_KEY_UNAVAILABLE_RESPONSE

        metadata = await _get_journal_entry_metadata(
            itgs,
            journal_entry_uid=args.journal_entry_uid,
            user_sub=std_auth_result.result.sub,
            read_consistency=args.min_consistency,
        )
        if metadata is None and args.min_consistency == "none":
            metadata = await _get_journal_entry_metadata(
                itgs,
                journal_entry_uid=args.journal_entry_uid,
                user_sub=std_auth_result.result.sub,
                read_consistency="weak",
            )

        if metadata is None:
            return ERROR_JOURNAL_ENTRY_NOT_FOUND_RESPONSE

        encrypted_payload = journal_client_key.journal_client_key.encrypt(
            metadata.__pydantic_serializer__.to_json(metadata)
        ).decode("ascii")
        return Response(
            content=ShowJournalMetadataResponse.__pydantic_serializer__.to_json(
                ShowJournalMetadataResponse(
                    encrypted_payload=encrypted_payload, payload=None
                )
            ),
            headers={
                "Content-Type": "application/json; charset=utf-8",
            },
            status_code=200,
        )


async def _get_journal_entry_metadata(
    itgs: Itgs,
    /,
    *,
    journal_entry_uid: str,
    user_sub: str,
    read_consistency: Literal["none", "weak", "strong"],
):
    conn = await itgs.conn()
    cursor = conn.cursor(read_consistency=read_consistency)
    response = await cursor.execute(
        """
SELECT
    journal_entries.created_at,
    journal_entries.canonical_at
FROM users, journal_entries
WHERE
    users.sub = ?
    AND users.id = journal_entries.user_Id
    AND journal_entries.uid = ?
        """,
        (user_sub, journal_entry_uid),
    )
    if not response.results:
        return None

    assert len(response.results) == 1, response

    created_at = cast(float, response.results[0][0])
    canonical_at = cast(float, response.results[0][1])
    return ShowJournalMetadataResponsePayload(
        uid=journal_entry_uid,
        created_at=created_at,
        canonical_at=canonical_at,
    )
