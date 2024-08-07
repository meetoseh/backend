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


class PopToJournalReflectionParameters(BaseModel):
    journal_entry_uid: str = Field(description="The UID of the journal entry to go to")


class PopToJournalReflectionParametersTriggerRequest(BaseModel):
    slug: str = Field(
        description="The slug of the client flow to trigger, assuming the user has access"
    )
    parameters: PopToJournalReflectionParameters = Field(
        description="The parameters to convert"
    )


class PopToJournalReflectionRequest(BaseModel):
    screen_jwt: str = Field(description="The JWT which lets you pop the screen")
    trigger: PopToJournalReflectionParametersTriggerRequest = Field(
        description=(
            "The client flow to trigger with server parameters set with the journal entry"
        ),
    )


@router.post(
    "/pop_to_journal_reflection",
    response_model=PeekScreenResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def pop_to_journal_reflection(
    args: PopToJournalReflectionRequest,
    platform: VisitorSource,
    version: Optional[int] = None,
    visitor: Annotated[Optional[str], Header()] = None,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Goes to the journal entry that belongs to the user with the given
    uid. If the journal entry does not exist or does not belong to the user,
    a different flow will be triggered and the response will still indicate
    success.

    If the journal entry does not have a reflection question and is not in the
    correct state to start generating one, a different flow will be triggered.
    Otherwise, we will ensure a reflection question has been generated or is
    being generated.

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
        queue_job_result = await lib.journals.start_journal_chat_job.add_journal_entry_reflection_question(
            itgs,
            journal_entry_uid=args.trigger.parameters.journal_entry_uid,
            user_sub=std_auth_result.result.sub,
            now=queue_job_at,
        )

        if queue_job_result.type == "journal_entry_not_found":
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

        if queue_job_result.type == "ratelimited" or queue_job_result.type == "locked":
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

        if queue_job_result.type != "success" and (
            queue_job_result.type != "bad_state"
            or queue_job_result.subtype != "already-has-reflection-question"
        ):
            await handle_warning(
                f"{__name__}:failed_to_queue",
                f"{std_auth_result.result.sub} failed to queue job to start journal chat job: {queue_job_result}",
            )
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
            expected_front_uid=screen_auth_result.result.user_client_screen_uid,
            user_sub=std_auth_result.result.sub,
            platform=platform,
            version=version,
            trigger=TrustedTrigger(
                flow_slug=args.trigger.slug,
                client_parameters={},
                server_parameters={
                    "journal_entry": args.trigger.parameters.journal_entry_uid,
                },
            ),
        )
        return await _realize(screen)
