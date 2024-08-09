import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from typing import Annotated, Optional, Literal
from auth import auth_any
from error_middleware import handle_warning
from itgs import Itgs
from models import (
    AUTHORIZATION_UNKNOWN_TOKEN,
    STANDARD_ERRORS_BY_CODE,
    StandardErrorResponse,
)
from pydantic import BaseModel, Field
import journals.chat_auth
import journals.entry_auth
import lib.journals.start_journal_chat_job
import journals.entry_auth
from visitors.lib.get_or_create_visitor import VisitorSource


router = APIRouter()


class SyncJournalEntryRequest(BaseModel):
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


class SyncJournalEntryResponse(BaseModel):
    journal_chat_jwt: str = Field(
        description=(
            "the JWT to provide to the websocket endpoint /api/2/journals/chat to "
            "retrieve the greeting"
        )
    )
    journal_entry_uid: str = Field(
        description="the UID of the journal entry that was created"
    )
    journal_entry_jwt: str = Field(
        description="a JWT that allows the user to respond to the journal entry"
    )


ERROR_404_TYPES = Literal["key_unavailable", "journal_entry_not_found"]
ERROR_KEY_UNAVAILABLE_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="key_unavailable",
        message="The provided journal client key is not available or is not acceptable for this transfer. Generate a new one.",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=404,
)
ERROR_JOURNAL_ENTRY_NOT_FOUND_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="journal_entry_not_found",
        message="There is no journal entry with that uid despite valid authorization; it has been deleted.",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=404,
)

ERROR_429_TYPES = Literal["ratelimited"]
ERROR_RATELIMITED_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_429_TYPES](
        type="ratelimited",
        message="You have been rate limited. Please try again later. Oseh+ users have less stringent limits",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=429,
)


@router.post(
    "/sync",
    response_model=SyncJournalEntryResponse,
    responses={
        "404": {
            "description": "If `type` is `key_unavailable`, then the provided journal client key is not available or is not acceptable for this transfer. Generate a new one.\n\n"
            "If `type` is `journal_entry_not_found`, then there is no journal entry with that uid despite valid authorization; it has been deleted.",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        "429": {
            "description": "You have been rate limited. Please try again later. Oseh+ users have less stringent limits",
            "model": StandardErrorResponse[ERROR_429_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def sync_journal_entry(
    args: SyncJournalEntryRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Returns the required information to stream the contents of the journal
    entry with the given uid, unchanged. This will use a journal client key as
    an additional encryption layer.

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
                f"User {std_auth_result.result.sub} tried to sync a journal entry with a greeting, but the JWT provided "
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
        queue_job_result = await lib.journals.start_journal_chat_job.sync_journal_entry(
            itgs,
            journal_entry_uid=args.journal_entry_uid,
            user_sub=std_auth_result.result.sub,
            now=queue_job_at,
        )

        if queue_job_result.type != "success" and queue_job_result.type != "locked":
            await handle_warning(
                f"{__name__}:queue_job_failed:{queue_job_result.type}",
                f"User {std_auth_result.result.sub} tried to sync a journal entry with a greeting, but "
                "we failed to queue the job",
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


async def journal_entry_sanity_precheck(
    itgs: Itgs,
    /,
    *,
    user_sub: str,
    journal_entry_uid: str,
    journal_client_key_uid: str,
    platform: str,
) -> Optional[Response]:
    """
    Verify the client key at least appears reasonable, without unnecessarily
    fetching it from s3. Returns None if it appears to be valid, or a Response
    if it is not.
    """

    conn = await itgs.conn()
    cursor = conn.cursor("weak")
    response = await cursor.executeunified3(
        (
            (
                """
SELECT
user_journal_client_keys.s3_file_id IS NOT NULL AS we_have_key,
user_journal_client_keys.platform = ? AS platform_matches
FROM users, user_journal_client_keys
WHERE
users.sub = ?
AND users.id = user_journal_client_keys.user_id
AND user_journal_client_keys.uid = ?
        """,
                (
                    platform,
                    user_sub,
                    journal_client_key_uid,
                ),
            ),
            (
                "SELECT 1 FROM users, journal_entries WHERE users.sub = ? AND journal_entries.uid = ? AND journal_entries.user_id = users.id",
                (user_sub, journal_entry_uid),
            ),
        )
    )
    if not response[0].results:
        await handle_warning(
            f"{__name__}:unknown_client_key",
            f"User {user_sub} tried to retrieve a journal entry using the journal client "
            f"key {journal_client_key_uid} for platform {platform}, but either the user has been deleted, "
            "we have never seen such a key, or it is for a different user",
        )
        return ERROR_KEY_UNAVAILABLE_RESPONSE

    we_have_key = bool(response[0].results[0][0])
    platform_matches = bool(response[0].results[0][1])

    if not we_have_key:
        await handle_warning(
            f"{__name__}:lost_client_key",
            f"User {user_sub} tried to retrieve a journal entry using the journal client "
            f"key {journal_client_key_uid} for platform {platform}, but we have "
            "deleted that key.",
        )
        return ERROR_KEY_UNAVAILABLE_RESPONSE

    if not platform_matches:
        await handle_warning(
            f"{__name__}:wrong_platform",
            f"User {user_sub} tried to sync a journal entry using the journal client "
            f"key {journal_client_key_uid} for platform {platform}, but that isn't the platform "
            "that created that key.",
        )
        return ERROR_KEY_UNAVAILABLE_RESPONSE

    journal_entry_exists = bool(response[1].results)
    if not journal_entry_exists:
        await handle_warning(
            f"{__name__}:journal_entry_not_found",
            f"User {user_sub} tried to sync a journal entry with uid {journal_entry_uid}, "
            "but we couldn't find it despite a valid jwt being provided",
        )
        return ERROR_JOURNAL_ENTRY_NOT_FOUND_RESPONSE
