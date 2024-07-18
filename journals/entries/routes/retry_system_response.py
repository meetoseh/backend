import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from typing import Annotated, Optional, Literal
from auth import auth_any
from error_middleware import handle_warning
from itgs import Itgs
from journals.entries.routes.create_journal_entry_user_chat import (
    CreateJournalEntryUserChatResponse,
)
from models import (
    AUTHORIZATION_UNKNOWN_TOKEN,
    STANDARD_ERRORS_BY_CODE,
    StandardErrorResponse,
)
from pydantic import BaseModel, Field
import journals.chat_auth
import journals.entry_auth
import lib.journals.start_journal_chat_job
from visitors.lib.get_or_create_visitor import VisitorSource


router = APIRouter()


class RetrySystemResponseRequest(BaseModel):
    platform: VisitorSource = Field(description="the platform the client is running on")
    journal_entry_uid: str = Field(
        description="The UID of the journal entry the user responded to"
    )
    journal_entry_jwt: str = Field(
        description="The JWT which allows the user to respond to that journal entry"
    )
    journal_client_key_uid: str = Field(
        description=(
            "the UID identifying which journal client key to use to encrypt "
            "the response from the system"
        )
    )


ERROR_404_TYPES = Literal["key_unavailable"]
ERROR_KEY_UNAVAILABLE_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="key_unavailable",
        message="The provided journal client key is not available or is not acceptable for this transfer. Generate a new one.",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=404,
)

ERROR_409_TYPES = Literal["journal_entry_bad_state"]
ERROR_JOURNAL_ENTRY_BAD_STATE = Response(
    content=StandardErrorResponse[ERROR_409_TYPES](
        type="journal_entry_bad_state",
        message="The provided journal entry is not in the correct state for this operation",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=409,
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
    "/chat/retry_system_response",
    response_model=CreateJournalEntryUserChatResponse,
    responses={
        "404": {
            "model": StandardErrorResponse[ERROR_404_TYPES],
            "description": "Either the provided journal client key is not available or is not acceptable for this transfer, or the journal entry could not be found.",
        },
        "409": {
            "model": StandardErrorResponse[ERROR_409_TYPES],
            "description": "The provided journal entry is not in the correct state for this operation",
        },
        "429": {
            "model": StandardErrorResponse[ERROR_429_TYPES],
            "description": (
                "The user has been rate limited. Oseh+ users have less stringent limits."
            ),
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def retry_system_response(
    args: RetrySystemResponseRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """When the user sends a chat message to a journal entry the same API request
    normally queues a job to get a response from the system. However, if the user
    is rate limited, their response will be stored but a job will not be queued.
    In that case, this endpoint can be used after a short period of time to queue
    the job to get a response from the system.

    Requires standard authorization for the same user that owns the journal entry
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

        if std_auth_result.result.sub != entry_auth_result.result.user_sub:
            return AUTHORIZATION_UNKNOWN_TOKEN

        if entry_auth_result.result.journal_entry_uid != args.journal_entry_uid:
            return AUTHORIZATION_UNKNOWN_TOKEN

        # Verify the client key at least appears reasonable, without unnecessarily
        # fetching it from s3
        conn = await itgs.conn()
        cursor = conn.cursor("weak")
        response = await cursor.execute(
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
            (args.platform, std_auth_result.result.sub, args.journal_client_key_uid),
        )
        if not response.results:
            await handle_warning(
                f"{__name__}:unknown_client_key",
                f"User `{std_auth_result.result.sub}` tried to request a system response using the journal client "
                f"key `{args.journal_client_key_uid}` for platform `{args.platform}`, but either the user has been deleted, "
                "we have never seen such a key, or it is for a different user",
            )
            return ERROR_KEY_UNAVAILABLE_RESPONSE

        we_have_key = bool(response.results[0][0])
        platform_matches = bool(response.results[0][1])

        if not we_have_key:
            await handle_warning(
                f"{__name__}:lost_client_key",
                f"User `{std_auth_result.result.sub}` tried to request a system response using the journal client "
                f"key `{args.journal_client_key_uid}` for platform `{args.platform}`, but we have "
                "deleted that key.",
            )
            return ERROR_KEY_UNAVAILABLE_RESPONSE

        if not platform_matches:
            await handle_warning(
                f"{__name__}:wrong_platform",
                f"User `{std_auth_result.result.sub}` tried to request a system response using the journal client "
                f"key `{args.journal_client_key_uid}` for platform `{args.platform}`, but that isn't the platform "
                "that created that key.",
            )
            return ERROR_KEY_UNAVAILABLE_RESPONSE

        queue_job_at = time.time()
        queue_job_result = (
            await lib.journals.start_journal_chat_job.add_journal_entry_chat(
                itgs,
                user_sub=std_auth_result.result.sub,
                journal_entry_uid=args.journal_entry_uid,
                now=queue_job_at,
            )
        )
        if queue_job_result.type != "success":
            await handle_warning(
                f"{__name__}:queue_job_failed:{queue_job_result.type}",
                f"User `{std_auth_result.result.sub}` retried a system chat message, "
                f"but we failed to queue the job: `{queue_job_result.type}`",
            )

            if queue_job_result.type == "ratelimited":
                return ERROR_RATELIMITED_RESPONSE
            if queue_job_result.type == "user_not_found":
                return AUTHORIZATION_UNKNOWN_TOKEN
            if queue_job_result.type == "bad_state":
                return ERROR_JOURNAL_ENTRY_BAD_STATE
            return Response(status_code=500)

        chat_jwt = await journals.chat_auth.create_jwt(
            itgs,
            user_sub=std_auth_result.result.sub,
            journal_entry_uid=args.journal_entry_uid,
            journal_chat_uid=queue_job_result.journal_chat_uid,
            journal_client_key_uid=args.journal_client_key_uid,
            audience="oseh-journal-chat",
        )
        entry_jwt = await journals.entry_auth.create_jwt(
            itgs,
            journal_entry_uid=args.journal_entry_uid,
            journal_client_key_uid=args.journal_client_key_uid,
            user_sub=std_auth_result.result.sub,
            audience="oseh-journal-entry",
        )
        return Response(
            content=CreateJournalEntryUserChatResponse(
                journal_chat_jwt=chat_jwt,
                journal_entry_uid=args.journal_entry_uid,
                journal_entry_jwt=entry_jwt,
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=200,
        )
