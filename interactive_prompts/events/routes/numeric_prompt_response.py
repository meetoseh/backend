from typing import Literal, Optional
from fastapi import APIRouter, Header
from fastapi import Response
from pydantic import BaseModel, Field
from interactive_prompts.events.models import (
    CreateInteractivePromptEventRequest,
    CreateInteractivePromptEventResponse,
    CREATE_INTERACTIVE_PROMPT_EVENT_STANDARD_ERRORS_BY_CODE,
    CREATE_INTERACTIVE_PROMPT_EVENT_409_TYPES,
)
import interactive_prompts.events.helper as evhelper
from itgs import Itgs
from models import StandardErrorResponse
from pypika import Query, Table, Parameter
from pypika.terms import ExistsCriterion
from pypika.functions import Function


class NumericPromptData(BaseModel):
    rating: int = Field(title="Rating", description="The rating given by the user.")


EventTypeT = Literal["numeric_prompt_response"]
EventRequestDataT = NumericPromptData
EventResponseDataT = NumericPromptData

router = APIRouter()


@router.post(
    "/respond_numeric_prompt",
    response_model=CreateInteractivePromptEventResponse[EventTypeT, EventResponseDataT],
    responses=CREATE_INTERACTIVE_PROMPT_EVENT_STANDARD_ERRORS_BY_CODE,
)
async def respond_to_interactive_prompt_numeric_prompt(
    args: CreateInteractivePromptEventRequest[EventRequestDataT],
    authorization: Optional[str] = Header(None),
):
    """Provides the given numeric response to the interactive prompt. Multiple
    numeric responses can be provided within a single session, but only if the
    interactive prompt has a numeric prompt.
    """
    async with Itgs() as itgs:
        auth_result = await evhelper.auth_create_interactive_prompt_event(
            itgs,
            authorization=authorization,
            interactive_prompt_jwt=args.interactive_prompt_jwt,
            interactive_prompt_uid=args.interactive_prompt_uid,
        )
        if auth_result.result is None:
            return auth_result.error_response

        interactive_prompt_sessions = Table("interactive_prompt_sessions")
        interactive_prompts = Table("interactive_prompts")

        result = await evhelper.create_interactive_prompt_event(
            itgs,
            interactive_prompt_uid=auth_result.result.interactive_prompt_uid,
            user_sub=auth_result.result.user_sub,
            session_uid=args.session_uid,
            event_type="numeric_prompt_response",
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
                            == "numeric"
                        )
                        .where(
                            Function(
                                "json_extract", interactive_prompts.prompt, "$.min"
                            )
                            <= Parameter("?")
                        )
                        .where(
                            Function(
                                "json_extract", interactive_prompts.prompt, "$.max"
                            )
                            >= Parameter("?")
                        )
                    ),
                    [args.data.rating, args.data.rating],
                )
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
                            == "numeric"
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
                                message=(
                                    "A numeric prompt response can only be provided to a "
                                    "numeric prompt interactive prompt."
                                ),
                            ).model_dump_json(),
                            headers={
                                "Content-Type": "application/json; charset=utf-8",
                            },
                            status_code=409,
                        ),
                    ),
                ),
                (
                    ExistsCriterion(
                        Query.from_(interactive_prompts)
                        .select(1)
                        .where(interactive_prompts.uid == Parameter("?"))
                        .where(
                            Function(
                                "json_extract", interactive_prompts.prompt, "$.min"
                            )
                            <= Parameter("?")
                        )
                        .where(
                            Function(
                                "json_extract", interactive_prompts.prompt, "$.max"
                            )
                            >= Parameter("?")
                        )
                    ),
                    [args.interactive_prompt_uid, args.data.rating, args.data.rating],
                    lambda: evhelper.CreateInteractivePromptEventResult(
                        result=None,
                        error_type="impossible_event_data",
                        error_response=Response(
                            content=StandardErrorResponse[
                                CREATE_INTERACTIVE_PROMPT_EVENT_409_TYPES
                            ](
                                type="impossible_event_data",
                                message=(
                                    "The given rating is outside of the range of the "
                                    "interactive prompt's numeric prompt."
                                ),
                            ).model_dump_json(),
                            headers={
                                "Content-Type": "application/json; charset=utf-8",
                            },
                            status_code=409,
                        ),
                    ),
                ),
            ],
            prefix_sum_updates=[
                evhelper.PrefixSumUpdate(
                    category="numeric_active",
                    amount=1,
                    simple=True,
                    category_value=args.data.rating,
                    event_type=None,
                    event_data_field=None,
                ),
                evhelper.PrefixSumUpdate(
                    category="numeric_active",
                    amount=-1,
                    simple=False,
                    category_value=None,
                    event_type="numeric_prompt_response",
                    event_data_field="rating",
                ),
            ],
        )
        if result.result is None:
            return result.error_response
        return result.result.response
