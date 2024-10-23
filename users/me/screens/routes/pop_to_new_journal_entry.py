import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, ConfigDict
from error_middleware import handle_warning
from lib.client_flows.executor import (
    ClientScreenQueuePeekInfo,
    TrustedTrigger,
    execute_peek,
    execute_pop,
)
from models import STANDARD_ERRORS_BY_CODE
from typing import Annotated, Literal, Optional
from itgs import Itgs
import auth as std_auth
import users.me.screens.auth

from users.me.screens.lib.realize_screens import realize_screens
from users.me.screens.models.peeked_screen import PeekScreenResponse
from visitors.lib.get_or_create_visitor import VisitorSource
import lib.journals.start_journal_chat_job


router = APIRouter()


class PopToNewJournalEntryParameters(BaseModel):
    initialize_with: Literal["greeting", "reflection-question"] = Field(
        "greeting",
        description="What to put as the initial content of the journal entry",
    )

    model_config = ConfigDict(extra="allow")


class PopToNewJournalEntryTriggerRequest(BaseModel):
    slug: str = Field(description="The slug of the client flow to trigger")
    parameters: PopToNewJournalEntryParameters = Field(
        description="The parameters to convert"
    )


class PopToNewJournalEntryRequest(BaseModel):
    screen_jwt: str = Field(description="The JWT which lets you pop the screen")
    trigger: PopToNewJournalEntryTriggerRequest = Field(
        description=(
            "The client flow to trigger with server parameters set to the journal entry uid"
        ),
    )


@router.post(
    "/pop_to_new_journal_entry",
    response_model=PeekScreenResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def pop_to_new_journal_entry(
    args: PopToNewJournalEntryRequest,
    platform: VisitorSource,
    version: Optional[int] = None,
    visitor: Annotated[Optional[str], Header()] = None,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """A specialized pop endpoint which creates a new journal entry for the user and
    then triggers the indicated flow with the new journal entry uid in the server
    parameters (as `journal_entry`).

    This can either initialize the journal entry with a greeting (for the journal chat
    screen) or with a reflection question (for the journal reflection large screen)

    Typically the journal entry uid will be converted to a journal chat JWT via
    the sync endpoint `/api/1/journals/entries/sync`, which allows connecting to
    the websocket endpoint `/api/2/journals/chat`, which will stream the state
    of the journal entry to the client. Then various sync-like endpoints (endpoints
    that largely accept and return the same structure) can be used to update the
    journal entry.

    Any extra parameters are forwarded as client parameters.

    Requires standard authorization for a user.
    """
    async with Itgs() as itgs:
        std_auth_result = await std_auth.auth_any(itgs, authorization)
        if std_auth_result.result is None:
            return std_auth_result.error_response

        user_sub = std_auth_result.result.sub

        async def _realize(screen: ClientScreenQueuePeekInfo):
            result = await realize_screens(
                itgs,
                user_sub=user_sub,
                platform=platform,
                visitor=visitor,
                result=screen,
            )

            return Response(
                content=result.__pydantic_serializer__.to_json(result),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=200,
            )

        screen_auth_result = await users.me.screens.auth.auth_any(
            itgs, args.screen_jwt, prefix=None
        )
        if screen_auth_result.result is None:
            screen = await execute_peek(
                itgs,
                user_sub=std_auth_result.result.sub,
                platform=platform,
                version=version,
                trigger=TrustedTrigger(
                    flow_slug="error_bad_auth",
                    client_parameters={},
                    server_parameters={},
                ),
            )
            return await _realize(screen)

        queue_job_at = time.time()
        if args.trigger.parameters.initialize_with == "greeting":
            queue_job_result = await lib.journals.start_journal_chat_job.create_journal_entry_with_greeting(
                itgs, user_sub=std_auth_result.result.sub, now=queue_job_at
            )
        else:
            queue_job_result = await lib.journals.start_journal_chat_job.create_journal_entry_with_reflection_question(
                itgs, user_sub=std_auth_result.result.sub, now=queue_job_at
            )

        if queue_job_result.type != "success":
            await handle_warning(
                f"{__name__}:queue_job_failed:{queue_job_result.type}",
                f"User `{std_auth_result.result.sub}` tried to create a journal entry with a greeting, but "
                "we failed to queue the job",
            )

        if queue_job_result.type == "ratelimited":
            screen = await execute_peek(
                itgs,
                user_sub=std_auth_result.result.sub,
                platform=platform,
                version=version,
                trigger=TrustedTrigger(
                    flow_slug="error_ratelimited",
                    client_parameters={},
                    server_parameters={},
                ),
            )
            return await _realize(screen)

        if queue_job_result.type == "user_not_found":
            return std_auth.AUTHORIZATION_UNKNOWN_TOKEN

        if (
            queue_job_result.type == "encryption_failed"
            or queue_job_result.type == "locked"
        ):
            screen = await execute_peek(
                itgs,
                user_sub=std_auth_result.result.sub,
                platform=platform,
                version=version,
                trigger=TrustedTrigger(
                    flow_slug="error_contact_support",
                    client_parameters={},
                    server_parameters={},
                ),
            )
            return await _realize(screen)

        screen = await execute_pop(
            itgs,
            user_sub=std_auth_result.result.sub,
            platform=platform,
            version=version,
            expected_front_uid=screen_auth_result.result.user_client_screen_uid,
            trigger=(
                TrustedTrigger(
                    flow_slug=args.trigger.slug,
                    client_parameters=args.trigger.parameters.model_extra or dict(),
                    server_parameters={
                        "journal_entry": queue_job_result.journal_entry_uid
                    },
                )
            ),
        )
        return await _realize(screen)
