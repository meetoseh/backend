from typing import Literal, Optional
from fastapi import APIRouter, Header
from fastapi import Response
from interactive_prompts.events.models import (
    CreateInteractivePromptEventRequest,
    CreateInteractivePromptEventResponse,
    NoInteractivePromptEventData,
    CREATE_INTERACTIVE_PROMPT_EVENT_STANDARD_ERRORS_BY_CODE,
    CREATE_INTERACTIVE_PROMPT_EVENT_409_TYPES,
)
import interactive_prompts.events.helper as evhelper
from itgs import Itgs
from models import StandardErrorResponse
from pypika import Query, Table, Parameter
from pypika.terms import ExistsCriterion
from pypika.functions import Function


EventTypeT = Literal["press_prompt_start_response"]
EventRequestDataT = NoInteractivePromptEventData
EventResponseDataT = NoInteractivePromptEventData

router = APIRouter()


@router.post(
    "/respond_press_prompt/start",
    response_model=CreateInteractivePromptEventResponse[EventTypeT, EventResponseDataT],
    responses=CREATE_INTERACTIVE_PROMPT_EVENT_STANDARD_ERRORS_BY_CODE,
)
async def respond_to_interactive_prompt_press_prompt_start(
    args: CreateInteractivePromptEventRequest[EventRequestDataT],
    authorization: Optional[str] = Header(None),
):
    """Indicates the user began pressing down on a interactive prompt press prompt,
    but only if the interactive prompt has a press prompt and the user is not
    already pressing down on the press prompt.
    """
    async with Itgs() as itgs:
        auth_result = await evhelper.auth_create_interactive_prompt_event(
            itgs,
            authorization=authorization,
            interactive_prompt_jwt=args.interactive_prompt_jwt,
            interactive_prompt_uid=args.interactive_prompt_uid,
        )
        if not auth_result.success:
            return auth_result.error_response

        interactive_prompt_sessions = Table("interactive_prompt_sessions")
        interactive_prompt_events = Table("interactive_prompt_events").as_("ipe")
        interactive_prompt_events_2 = Table("interactive_prompt_events").as_("ipe2")
        interactive_prompts = Table("interactive_prompts")

        result = await evhelper.create_interactive_prompt_event(
            itgs,
            interactive_prompt_uid=auth_result.result.interactive_prompt_uid,
            user_sub=auth_result.result.user_sub,
            session_uid=args.session_uid,
            event_type="press_prompt_start_response",
            event_data=args.data,
            prompt_time=args.prompt_time,
            bonus_terms=[
                (
                    ExistsCriterion(
                        Query.from_(interactive_prompts)
                        .select(1)
                        .where(
                            interactive_prompts.id
                            == interactive_prompt_sessions.interactive_prompt_id
                        )
                        .where(
                            Function(
                                "json_extract", interactive_prompts.prompt, "$.style"
                            )
                            == "press"
                        )
                    ),
                    [],
                ),
                (
                    ~ExistsCriterion(
                        Query.from_(interactive_prompt_events)
                        .select(1)
                        .where(
                            interactive_prompt_events.interactive_prompt_session_id
                            == interactive_prompt_sessions.id
                        )
                        .where(
                            interactive_prompt_events.evtype
                            == "press_prompt_start_response"
                        )
                        .where(
                            ~ExistsCriterion(
                                Query.from_(interactive_prompt_events_2)
                                .select(1)
                                .where(
                                    interactive_prompt_events_2.interactive_prompt_session_id
                                    == interactive_prompt_sessions.id
                                )
                                .where(
                                    interactive_prompt_events_2.prompt_time
                                    > interactive_prompt_events.prompt_time
                                )
                                .where(
                                    interactive_prompt_events_2.evtype
                                    == "press_prompt_end_response"
                                )
                            )
                        )
                    ),
                    [],
                ),
            ],
            bonus_error_checks=[
                (
                    ExistsCriterion(
                        Query.from_(interactive_prompts)
                        .select(1)
                        .where(interactive_prompts.uid == Parameter("?"))
                        .where(
                            Function(
                                "json_extract", interactive_prompts.prompt, "$.style"
                            )
                            == "press"
                        )
                    ),
                    [args.interactive_prompt_uid],
                    lambda: evhelper.CreateInteractivePromptEventResult(
                        result=None,
                        error_type="impossible_event",
                        error_response=Response(
                            content=StandardErrorResponse[
                                CREATE_INTERACTIVE_PROMPT_EVENT_409_TYPES
                            ](
                                type="impossible_event",
                                message="A press prompt start event requires the interactive prompt has a press prompt",
                            ).json(),
                            headers={"Content-Type": "application/json; charset=utf-8"},
                            status_code=409,
                        ),
                    ),
                ),
                (
                    ~ExistsCriterion(
                        Query.from_(interactive_prompt_events)
                        .select(1)
                        .where(
                            ExistsCriterion(
                                Query.from_(interactive_prompt_sessions)
                                .select(1)
                                .where(
                                    interactive_prompt_sessions.uid == Parameter("?")
                                )
                                .where(
                                    interactive_prompt_sessions.id
                                    == interactive_prompt_events.interactive_prompt_session_id
                                )
                            )
                        )
                        .where(
                            interactive_prompt_events.evtype
                            == "press_prompt_start_response"
                        )
                        .where(
                            ~ExistsCriterion(
                                Query.from_(interactive_prompt_events_2)
                                .select(1)
                                .where(
                                    interactive_prompt_events_2.interactive_prompt_session_id
                                    == interactive_prompt_events.interactive_prompt_session_id
                                )
                                .where(
                                    interactive_prompt_events_2.prompt_time
                                    > interactive_prompt_events.prompt_time
                                )
                                .where(
                                    interactive_prompt_events_2.evtype
                                    == "press_prompt_end_response"
                                )
                            )
                        )
                    ),
                    [args.session_uid],
                    lambda: evhelper.CreateInteractivePromptEventResult(
                        result=None,
                        error_type="impossible_event_data",
                        error_response=Response(
                            content=StandardErrorResponse[
                                CREATE_INTERACTIVE_PROMPT_EVENT_409_TYPES
                            ](
                                type="impossible_event_data",
                                message=(
                                    "The user is already pressing down on the press prompt."
                                ),
                            ).json(),
                            headers={"Content-Type": "application/json; charset=UTF-8"},
                            status_code=409,
                        ),
                    ),
                ),
            ],
            prefix_sum_updates=[
                evhelper.PrefixSumUpdate(
                    category="press_active",
                    amount=1,
                    simple=True,
                    category_value=None,
                    event_type=None,
                    event_data_field=None,
                ),
                evhelper.PrefixSumUpdate(
                    category="press",
                    amount=1,
                    simple=True,
                    category_value=None,
                    event_type=None,
                    event_data_field=None,
                ),
            ],
        )
        if not result.success:
            return result.error_response
        return result.result.response
