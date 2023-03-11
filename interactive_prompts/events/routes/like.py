from typing import Literal, Optional
from fastapi import APIRouter, Header
from interactive_prompts.events.models import (
    CreateInteractivePromptEventRequest,
    CreateInteractivePromptEventResponse,
    NoInteractivePromptEventData,
    CREATE_INTERACTIVE_PROMPT_EVENT_STANDARD_ERRORS_BY_CODE,
)
import interactive_prompts.events.helper
from itgs import Itgs

EventTypeT = Literal["like"]
EventRequestDataT = NoInteractivePromptEventData
EventResponseDataT = NoInteractivePromptEventData

router = APIRouter()


@router.post(
    "/like",
    response_model=CreateInteractivePromptEventResponse[EventTypeT, EventResponseDataT],
    responses=CREATE_INTERACTIVE_PROMPT_EVENT_STANDARD_ERRORS_BY_CODE,
)
async def like_interactive_prompt(
    args: CreateInteractivePromptEventRequest[EventRequestDataT],
    authorization: Optional[str] = Header(None),
):
    """Marks that the given user tapped the like button for the given interactive prompt.
    A user can tap the like button multiple times to produce independent like events.
    """
    async with Itgs() as itgs:
        auth_result = await interactive_prompts.events.helper.auth_create_interactive_prompt_event(
            itgs,
            authorization=authorization,
            interactive_prompt_jwt=args.interactive_prompt_jwt,
            interactive_prompt_uid=args.interactive_prompt_uid,
        )
        if not auth_result.success:
            return auth_result.error_response

        result = (
            await interactive_prompts.events.helper.create_interactive_prompt_event(
                itgs,
                interactive_prompt_uid=auth_result.result.interactive_prompt_uid,
                user_sub=auth_result.result.user_sub,
                session_uid=args.session_uid,
                event_type="like",
                event_data=args.data,
                prompt_time=args.prompt_time,
                prefix_sum_updates=[
                    interactive_prompts.events.helper.PrefixSumUpdate(
                        category="likes",
                        amount=1,
                        simple=True,
                        category_value=None,
                        event_type=None,
                        event_data_field=None,
                    )
                ],
            )
        )
        if not result.success:
            return result.error_response
        return result.result.response
