import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from typing import Annotated, Optional

from pydantic import BaseModel, Field
from auth import auth_any
from error_middleware import handle_warning
from itgs import Itgs
from journals.entries.routes.sync_journal_entry import (
    ERROR_429_TYPES,
    ERROR_JOURNAL_ENTRY_NOT_FOUND_RESPONSE,
    ERROR_KEY_UNAVAILABLE_RESPONSE,
    ERROR_RATELIMITED_RESPONSE,
    SyncJournalEntryResponse,
)
from journals.entries.routes.edit_reflection_question import (
    ERROR_404_TYPES,
    ERROR_500_TYPES,
    ERROR_BAD_STATE_RESPONSE,
)
from lib.journals.edit_entry_item import (
    EditEntryItemDecryptedTextToTextualItem,
    edit_entry_item,
)
from models import (
    AUTHORIZATION_UNKNOWN_TOKEN,
    STANDARD_ERRORS_BY_CODE,
    StandardErrorResponse,
)
import journals.chat_auth
import journals.entry_auth
import lib.journals.start_journal_chat_job
import journals.entry_auth
from visitors.lib.get_or_create_visitor import VisitorSource


class EditReflectionResponseRequest(BaseModel):
    platform: VisitorSource = Field(description="the platform the client is running on")
    journal_client_key_uid: str = Field(
        description=(
            "the UID identifying which journal client key to use an "
            "additional layer of encryption"
        )
    )
    journal_entry_uid: str = Field(
        description="the UID of the journal entry that was created"
    )
    journal_entry_jwt: str = Field(
        description="a JWT that allows the user to respond to the journal entry"
    )
    entry_counter: int = Field(
        description="The entry counter of the item within the journal to edit"
    )
    encrypted_reflection_response: str = Field(
        description="The new value of the reflection response, encrypted with the client key"
    )


router = APIRouter()


@router.post(
    "/edit_reflection_response",
    response_model=SyncJournalEntryResponse,
    responses={
        "404": {
            "description": """Further distinguished using `type`:

- `key_unavailable`: the provided journal client key is not available or is not acceptable for this transfer. Generate a new one.
- `journal_entry_not_found`: there is no journal entry with that uid despite valid authorization; it has been deleted.
- `journal_entry_item_not_found`: the journal entry exists, but either the entry indicated doesn't exist,
  or isn't a reflection question
""",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        "429": {
            "description": "You have been rate limited. Please try again later. Oseh+ users have less stringent limits",
            "model": StandardErrorResponse[ERROR_429_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def edit_reflection_response(
    args: EditReflectionResponseRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Edits the indicated reflection response and returns the JWT required to stream
    the new state of the entry. The client MAY skip streaming the entry and instead choose
    to update the entry client-side after a successful response, but only if they are careful
    to trim the reflection response and break paragraphs.

    Requires standard authorization for the user that the journal entry belongs to,
    plus an additional JWT authorizing viewing that journal entry.
    """
    async with Itgs() as itgs:
        std_auth_result = await auth_any(itgs, authorization)
        if std_auth_result.result is None:
            return std_auth_result.error_response

        entry_auth_result = await journals.entry_auth.auth_any(
            itgs, f"bearer {args.journal_entry_jwt}"
        )
        if entry_auth_result.result is None:
            return entry_auth_result.error_response

        if entry_auth_result.result.journal_entry_uid != args.journal_entry_uid:
            return AUTHORIZATION_UNKNOWN_TOKEN

        if entry_auth_result.result.user_sub != std_auth_result.result.sub:
            await handle_warning(
                f"{__name__}:stolen_jwt",
                f"User {std_auth_result.result.sub} tried to sync + ensure a reflection question, but the JWT provided "
                f"was for a different user ({entry_auth_result.result.user_sub})",
                is_urgent=True,
            )
            return AUTHORIZATION_UNKNOWN_TOKEN

        edit_result = await edit_entry_item(
            itgs,
            user_sub=std_auth_result.result.sub,
            journal_entry_uid=args.journal_entry_uid,
            entry_counter=args.entry_counter,
            journal_client_key_uid=args.journal_client_key_uid,
            platform=args.platform,
            encrypted_text=args.encrypted_reflection_response,
            expected_type="reflection-response",
            decrypted_text_to_item=EditEntryItemDecryptedTextToTextualItem(
                "reflection-response", "self"
            ),
        )
        if edit_result.type == "user_not_found":
            return AUTHORIZATION_UNKNOWN_TOKEN
        if edit_result.type == "journal_entry_not_found":
            return ERROR_JOURNAL_ENTRY_NOT_FOUND_RESPONSE
        if edit_result.type == "journal_entry_item_not_found":
            return Response(
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="journal_entry_item_not_found",
                    message="The provided journal entry item does not exist",
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=404,
            )
        if edit_result.type == "client_key_rejected":
            return ERROR_KEY_UNAVAILABLE_RESPONSE
        if edit_result.type == "journal_entry_item_bad_type":
            return ERROR_BAD_STATE_RESPONSE
        if edit_result.type != "success":
            return Response(
                content=StandardErrorResponse[ERROR_500_TYPES](
                    type="contact_support",
                    message="An internal error occurred. Please contact support.",
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=500,
            )

        queue_job_at = time.time()
        queue_job_result = await lib.journals.start_journal_chat_job.sync_journal_entry(
            itgs,
            journal_entry_uid=args.journal_entry_uid,
            user_sub=std_auth_result.result.sub,
            now=queue_job_at,
        )

        if queue_job_result.type != "success":
            await handle_warning(
                f"{__name__}:queue_job_failed:{queue_job_result.type}",
                f"User `{std_auth_result.result.sub}` tried to retrieve a journal entry, but we failed to queue the job",
            )

            if (
                queue_job_result.type == "ratelimited"
                or queue_job_result.type == "locked"
            ):
                return ERROR_RATELIMITED_RESPONSE
            if queue_job_result.type == "user_not_found":
                return AUTHORIZATION_UNKNOWN_TOKEN
            return Response(status_code=500)

        chat_jwt = await journals.chat_auth.create_jwt(
            itgs,
            user_sub=std_auth_result.result.sub,
            journal_entry_uid=args.journal_entry_uid,
            journal_chat_uid=queue_job_result.journal_chat_uid,
            journal_client_key_uid=args.journal_client_key_uid,
            audience="oseh-journal-chat",
        )
        return Response(
            content=SyncJournalEntryResponse(
                journal_chat_jwt=chat_jwt,
                journal_entry_uid=args.journal_entry_uid,
                journal_entry_jwt=args.journal_entry_jwt,
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=200,
        )
