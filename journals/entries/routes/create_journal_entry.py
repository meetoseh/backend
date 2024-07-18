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
from visitors.lib.get_or_create_visitor import VisitorSource


router = APIRouter()


class CreateJournalEntryRequest(BaseModel):
    platform: VisitorSource = Field(description="the platform the client is running on")
    journal_client_key_uid: str = Field(
        description=(
            "the UID identifying which journal client key to use an "
            "additional layer of encryption when sending back the systems greeting"
        )
    )


class CreateJournalEntryResponse(BaseModel):
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


ERROR_404_TYPES = Literal["key_unavailable"]
ERROR_KEY_UNAVAILABLE_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="key_unavailable",
        message="The provided journal client key is not available or is not acceptable for this transfer. Generate a new one.",
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
    "/",
    response_model=CreateJournalEntryResponse,
    responses={
        "404": {
            "description": "The provided journal client key is not available or is not acceptable for this transfer. Generate a new one.",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        "429": {
            "description": "You have been rate limited. Please try again later. Oseh+ users have less stringent limits",
            "model": StandardErrorResponse[ERROR_429_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def create_journal_entry(
    args: CreateJournalEntryRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Creates a new journal entry for the user. Journal entries are seeded with
    a greeting to help the user get started. This greeting may be personalized and
    timely. The greeting may take some time to generate and as such this endpoint
    returns a JWT that can be provided to the websocket endpoint
    /api/2/journals/chat to retrieve the state of the newly created
    conversation.

    All journal entry text, including system messages, are always encrypted
    during storage and transmission, including in our database and shared caches
    (such as redis). We use different keys for client to server communication vs
    internal only communication. Client communication is TLS augmented with
    per-user-per-device keys, whereas internal communication is
    per-user-with-rotation. We depend on TLS not to be compromised to avoid
    leaking any data and to protect against active attacks (ie., using the bearer
    token), but are resistant to passive attacks (i.e., actors who aren't
    specifically targetting Oseh) even with compromised TLS (such as via an
    inappropriately trusted certificate authority on the clients device).
    Clients only keep journal data ephemerally and keep their keys in the most
    secure available location (e.g., on native iOS, protected by the secure
    enclave).

    Within ephemeral stores (i.e., memory and cpu caches), the data is only kept
    unencrypted for the minimal amount of time required to process the request.

    The encryption keys are transiently available unencrypted in ephemeral
    storage (such as memory or cpu caches) and permanently located in
    independent files in a private (all public access blocked) Amazon S3 bucket,
    which encrypts with one of the strongest block ciphers available (AES-256)
    with a root key that is regularly rotated

    Limited metadata about journal entries are kept unencrypted in the database
    and caches in order to facilitate rapid indexing and retrieval, such as the
    number of journal entries for a user, the number of items within journal entries, and
    when such items or entries were created. Furthermore, some limited information can be
    deduced knowing only the encrypted representation of the contents, such as its approximate
    length (i.e., a 1kb encrypted blob contains less text than a 128kb one, but the
    actual text itself cannot be known without the key).

    Aggregate statistics about the number of users who have provided messages of
    lengths within certain ranges (e.g., how many users created a 20-99 character
    message within a day) are also kept, though even with attempts to disaggregate,
    this would not expose significantly more granularity than is already available
    as described before.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

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
            (args.platform, auth_result.result.sub, args.journal_client_key_uid),
        )
        if not response.results:
            await handle_warning(
                f"{__name__}:unknown_client_key",
                f"User {auth_result.result.sub} tried to create a journal entry using the journal client "
                f"key {args.journal_client_key_uid} for platform {args.platform}, but either the user has been deleted, "
                "we have never seen such a key, or it is for a different user",
            )
            return ERROR_KEY_UNAVAILABLE_RESPONSE

        we_have_key = bool(response.results[0][0])
        platform_matches = bool(response.results[0][1])

        if not we_have_key:
            await handle_warning(
                f"{__name__}:lost_client_key",
                f"User {auth_result.result.sub} tried to create a journal entry using the journal client "
                f"key {args.journal_client_key_uid} for platform {args.platform}, but we have "
                "deleted that key.",
            )
            return ERROR_KEY_UNAVAILABLE_RESPONSE

        if not platform_matches:
            await handle_warning(
                f"{__name__}:wrong_platform",
                f"User {auth_result.result.sub} tried to create a journal entry using the journal client "
                f"key {args.journal_client_key_uid} for platform {args.platform}, but that isn't the platform "
                "that created that key.",
            )
            return ERROR_KEY_UNAVAILABLE_RESPONSE

        queue_job_at = time.time()
        queue_job_result = await lib.journals.start_journal_chat_job.create_journal_entry_with_greeting(
            itgs, user_sub=auth_result.result.sub, now=queue_job_at
        )

        if queue_job_result.type != "success":
            await handle_warning(
                f"{__name__}:queue_job_failed:{queue_job_result.type}",
                f"User {auth_result.result.sub} tried to create a journal entry with a greeting, but "
                "we failed to queue the job",
            )

            if queue_job_result.type == "ratelimited":
                return ERROR_RATELIMITED_RESPONSE
            if queue_job_result.type == "user_not_found":
                return AUTHORIZATION_UNKNOWN_TOKEN
            return Response(status_code=500)

        chat_jwt = await journals.chat_auth.create_jwt(
            itgs,
            user_sub=auth_result.result.sub,
            journal_entry_uid=queue_job_result.journal_entry_uid,
            journal_chat_uid=queue_job_result.journal_chat_uid,
            journal_client_key_uid=args.journal_client_key_uid,
            audience="oseh-journal-chat",
        )
        entry_jwt = await journals.entry_auth.create_jwt(
            itgs,
            journal_entry_uid=queue_job_result.journal_entry_uid,
            journal_client_key_uid=args.journal_client_key_uid,
            user_sub=auth_result.result.sub,
            audience="oseh-journal-entry",
        )
        return Response(
            content=CreateJournalEntryResponse(
                journal_chat_jwt=chat_jwt,
                journal_entry_uid=queue_job_result.journal_entry_uid,
                journal_entry_jwt=entry_jwt,
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=200,
        )
