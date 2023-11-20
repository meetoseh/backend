from typing import Literal, Optional
from fastapi import APIRouter, Header
from interactive_prompts.events.models import (
    CreateInteractivePromptEventRequest,
    CreateInteractivePromptEventResponse,
    NameEventData,
    NoInteractivePromptEventData,
    CREATE_INTERACTIVE_PROMPT_EVENT_STANDARD_ERRORS_BY_CODE,
)
import interactive_prompts.events.helper
from itgs import Itgs

EventTypeT = Literal["leave"]
EventRequestDataT = NoInteractivePromptEventData
EventResponseDataT = NameEventData

router = APIRouter()


@router.post(
    "/leave",
    response_model=CreateInteractivePromptEventResponse[EventTypeT, EventResponseDataT],
    responses=CREATE_INTERACTIVE_PROMPT_EVENT_STANDARD_ERRORS_BY_CODE,
)
async def leave_interactive_prompt(
    args: CreateInteractivePromptEventRequest[EventRequestDataT],
    authorization: Optional[str] = Header(None),
):
    """Marks that the given user left the given interactive prompt. A user can leave a
    session only once, after only after joining.
    """
    async with Itgs() as itgs:
        auth_result = await interactive_prompts.events.helper.auth_create_interactive_prompt_event(
            itgs,
            authorization=authorization,
            interactive_prompt_jwt=args.interactive_prompt_jwt,
            interactive_prompt_uid=args.interactive_prompt_uid,
        )
        if auth_result.result is None:
            return auth_result.error_response

        display_name = await interactive_prompts.events.helper.get_display_name(
            itgs, auth_result.result
        )

        result = (
            await interactive_prompts.events.helper.create_interactive_prompt_event(
                itgs,
                interactive_prompt_uid=auth_result.result.interactive_prompt_uid,
                user_sub=auth_result.result.user_sub,
                session_uid=args.session_uid,
                event_type="leave",
                event_data=NameEventData(name=display_name),
                prompt_time=args.prompt_time,
                prefix_sum_updates=[
                    interactive_prompts.events.helper.PrefixSumUpdate(
                        category="users",
                        amount=-1,
                        simple=True,
                        category_value=None,
                        event_type=None,
                        event_data_field=None,
                    )
                ],
                store_event_data=NoInteractivePromptEventData(),
            )
        )
        if result.result is None:
            return result.error_response
        return result.result.response
