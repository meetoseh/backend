import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from typing import Annotated, Optional
from pydantic import BaseModel, Field

from error_middleware import handle_warning
from lib.client_flows.executor import (
    ClientScreenQueuePeekInfo,
    TrustedTrigger,
    execute_peek,
    execute_pop,
)
from models import STANDARD_ERRORS_BY_CODE
from users.me.screens.lib.realize_screens import realize_screens
from users.me.screens.models.peeked_screen import PeekScreenResponse
from visitors.lib.get_or_create_visitor import VisitorSource
import auth as std_auth
from itgs import Itgs
import users.me.screens.auth
import lib.journals.start_journal_chat_job

router = APIRouter()


class PopFromJournalReflectionParameters(BaseModel):
    journal_entry_uid: str = Field(
        description="The UID of the journal entry whose reflection response was just added"
    )
    forward_journal_entry_uid: bool = Field(
        False,
        description="If true, the journal entry uid is included (as `journal_entry`) in the server parameters for the next screen if it can be validated, otherwise not_found is triggered instead",
    )


class PopFromJournalReflectionParametersTriggerRequest(BaseModel):
    slug: str = Field(
        description="The slug of the client flow to trigger, assuming the user has access"
    )
    parameters: PopFromJournalReflectionParameters = Field(
        description="The parameters to convert"
    )


class PopFromJournalReflectionRequest(BaseModel):
    screen_jwt: str = Field(description="The JWT which lets you pop the screen")
    trigger: PopFromJournalReflectionParametersTriggerRequest = Field(
        description="The client flow to trigger",
    )


@router.post(
    "/pop_from_journal_reflection",
    response_model=PeekScreenResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def pop_from_journal_reflection(
    args: PopFromJournalReflectionRequest,
    platform: VisitorSource,
    version: Optional[int] = None,
    visitor: Annotated[Optional[str], Header()] = None,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Intended to be used as an endpoint target from the JournalReflectionResponse
    screen, or at some point after it, in order to queue a journal chat job to
    generate a summary for the corresponding journal entry. All screens are
    intended to be self-healing if the journal entry is missing the last
    automated step, so this endpoint can always be omitted without _breaking_
    the client, however, it will improve the experience if, when they e.g. go to
    my journal, all the summaries are already there.

    Provides no parameters to the client flow triggered

    Requires standard authorization for a user that owns the journal entry
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
        queue_job_result = (
            await lib.journals.start_journal_chat_job.add_journal_entry_summary(
                itgs,
                journal_entry_uid=args.trigger.parameters.journal_entry_uid,
                user_sub=std_auth_result.result.sub,
                now=queue_job_at,
            )
        )

        if queue_job_result.type != "success":
            if queue_job_result.type != "bad_state":
                await handle_warning(
                    f"{__name__}:failed_to_queue",
                    f"{std_auth_result.result.sub} failed to queue job to start journal chat job: {queue_job_result}",
                )

            if (
                args.trigger.parameters.forward_journal_entry_uid
                and queue_job_result.type != "bad_state"
            ):
                screen = await execute_peek(
                    itgs,
                    user_sub=std_auth_result.result.sub,
                    platform=platform,
                    version=version,
                    trigger=TrustedTrigger(
                        flow_slug="not_found",
                        client_parameters={},
                        server_parameters={},
                    ),
                )
                return await _realize(screen)

        screen = await execute_pop(
            itgs,
            expected_front_uid=screen_auth_result.result.user_client_screen_uid,
            user_sub=std_auth_result.result.sub,
            platform=platform,
            version=version,
            trigger=TrustedTrigger(
                flow_slug=args.trigger.slug,
                client_parameters={},
                server_parameters=(
                    {"journal_entry": args.trigger.parameters.journal_entry_uid}
                    if args.trigger.parameters.forward_journal_entry_uid
                    else {}
                ),
            ),
        )
        return await _realize(screen)
