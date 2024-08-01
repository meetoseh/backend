from fastapi import APIRouter, Header
from fastapi.responses import Response
from typing import Annotated, Optional
from pydantic import BaseModel, Field

from lib.client_flows.executor import (
    ClientScreenQueuePeekInfo,
    TrustedTrigger,
    execute_peek,
)
from models import STANDARD_ERRORS_BY_CODE
from users.me.screens.lib.realize_screens import realize_screens
from users.me.screens.models.peeked_screen import PeekScreenResponse
from visitors.lib.get_or_create_visitor import VisitorSource
import auth as std_auth
from itgs import Itgs
import users.me.screens.auth

router = APIRouter()


class PopToExistingJournalEntryParameters(BaseModel):
    journal_entry_uid: str = Field(description="The UID of the journal entry to go to")


class PopToExistingJournalEntryParametersTriggerRequest(BaseModel):
    slug: str = Field(
        description="The slug of the client flow to trigger, assuming the user has access"
    )
    parameters: PopToExistingJournalEntryParameters = Field(
        description="The parameters to convert"
    )


class PopToExistingJournalEntryRequest(BaseModel):
    screen_jwt: str = Field(description="The JWT which lets you pop the screen")
    trigger: PopToExistingJournalEntryParametersTriggerRequest = Field(
        description=(
            "The client flow to trigger with server parameters set with the journal entry"
        ),
    )


@router.post(
    "/pop_to_existing_journal_entry",
    response_model=PeekScreenResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def pop_to_existing_journal_entry(
    args: PopToExistingJournalEntryRequest,
    platform: VisitorSource,
    version: Optional[int] = None,
    visitor: Annotated[Optional[str], Header()] = None,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Goes to the journal entry that belongs to the user with the given
    uid. If the journal entry does not exist or does not belong to the user,
    a different flow will be triggered and the response will still indicate
    success.

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

        conn = await itgs.conn()
        cursor = conn.cursor("weak")

        response = await cursor.execute(
            """
SELECT 1 FROM users, journal_entries
WHERE
    users.sub = ?
    AND users.id = journal_entries.user_id
    AND journal_entries.uid = ?
            """,
            (
                user_sub,
                args.trigger.parameters.journal_entry_uid,
            ),
        )
        if not response.results:
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

        screen = await execute_peek(
            itgs,
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
