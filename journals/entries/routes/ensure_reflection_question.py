import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from typing import Annotated, Optional, Literal
from auth import auth_any
from error_middleware import handle_warning
from itgs import Itgs
from journals.entries.routes.sync_journal_entry import (
    ERROR_404_TYPES,
    ERROR_429_TYPES,
    ERROR_RATELIMITED_RESPONSE,
    SyncJournalEntryRequest,
    SyncJournalEntryResponse,
    journal_entry_sanity_precheck,
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


router = APIRouter()


ERROR_409_TYPES = Literal["bad_state"]
ERROR_BAD_STATE_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_409_TYPES](
        type="bad_state",
        message="The provided journal entry is not in the correct state for this operation",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=409,
)


@router.post(
    "/ensure_reflection_question",
    response_model=SyncJournalEntryResponse,
    responses={
        "404": {
            "description": "If `type` is `key_unavailable`, then the provided journal client key is not available or is not acceptable for this transfer. Generate a new one.\n\n"
            "If `type` is `journal_entry_not_found`, then there is no journal entry with that uid despite valid authorization; it has been deleted.",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        "409": {
            "description": "The provided journal entry is not in the correct state for this operation. For example, the user hasn't taken a class, so we can't make a reflection question about it",
            "model": StandardErrorResponse[ERROR_409_TYPES],
        },
        "429": {
            "description": "You have been rate limited. Please try again later. Oseh+ users have less stringent limits",
            "model": StandardErrorResponse[ERROR_429_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def ensure_reflection_question(
    args: SyncJournalEntryRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Returns the required information to stream the contents of the journal
    entry with the given uid. If the journal entry is in the correct state to
    add a reflection question, one is generated and added to the end of the
    entry. This will use a journal client key as an additional encryption layer.

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

        precheck = await journal_entry_sanity_precheck(
            itgs,
            user_sub=std_auth_result.result.sub,
            journal_entry_uid=args.journal_entry_uid,
            journal_client_key_uid=args.journal_client_key_uid,
            platform=args.platform,
        )
        if precheck is not None:
            return precheck

        queue_job_at = time.time()
        queue_job_result = await lib.journals.start_journal_chat_job.add_journal_entry_reflection_question(
            itgs,
            journal_entry_uid=args.journal_entry_uid,
            user_sub=std_auth_result.result.sub,
            now=queue_job_at,
        )

        if queue_job_result.type == "bad_state":
            if queue_job_result.subtype == "already-has-reflection-question":
                queue_job_at = time.time()
                queue_job_result = (
                    await lib.journals.start_journal_chat_job.sync_journal_entry(
                        itgs,
                        journal_entry_uid=args.journal_entry_uid,
                        user_sub=std_auth_result.result.sub,
                        now=queue_job_at,
                    )
                )
            else:
                await handle_warning(
                    f"{__name__}:bad_state:{queue_job_result.subtype}",
                    f"User `{std_auth_result.result.sub}` tried to retrieve a journal entry, ensuring it has "
                    "a reflection question, but it is not in the right state to have one",
                )
                return ERROR_BAD_STATE_RESPONSE

        if queue_job_result.type != "success" and queue_job_result.type != "locked":
            await handle_warning(
                f"{__name__}:queue_job_failed:{queue_job_result.type}",
                f"User `{std_auth_result.result.sub}` tried to retrieve a journal entry, but we failed to queue the job",
            )

            if queue_job_result.type == "ratelimited":
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
