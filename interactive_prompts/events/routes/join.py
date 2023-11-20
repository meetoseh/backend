from typing import Literal, Optional, cast as typing_cast
from fastapi import APIRouter, Header
from fastapi.responses import Response
from interactive_prompts.events.models import (
    CreateInteractivePromptEventRequest,
    CreateInteractivePromptEventResponse,
    NameEventData,
    NoInteractivePromptEventData,
    CREATE_INTERACTIVE_PROMPT_EVENT_STANDARD_ERRORS_BY_CODE,
    ERROR_INTERACTIVE_PROMPT_NOT_FOUND_RESPONSE,
)
import interactive_prompts.events.helper
from interactive_prompts.lib.read_interactive_prompt_meta import (
    read_interactive_prompt_meta,
)
from itgs import Itgs
from models import StandardErrorResponse
import users.lib.stats
import interactive_prompts.lib.stats

EventTypeT = Literal["join"]
EventRequestDataT = NoInteractivePromptEventData
EventResponseDataT = NameEventData

router = APIRouter()


ERROR_503_TYPES = Literal["user_not_found"]


@router.post(
    "/join",
    response_model=CreateInteractivePromptEventResponse[EventTypeT, EventResponseDataT],
    responses=CREATE_INTERACTIVE_PROMPT_EVENT_STANDARD_ERRORS_BY_CODE,
)
async def join_interactive_prompt(
    args: CreateInteractivePromptEventRequest[EventRequestDataT],
    authorization: Optional[str] = Header(None),
):
    """Marks that the given user joined the given interactive prompt. A user can join an
    interactive prompt multiple times, but only in separate sessions.
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

        # required for stats
        user_created_at = await get_user_created_at(
            itgs, sub=auth_result.result.user_sub
        )

        if user_created_at is None:
            return Response(
                content=StandardErrorResponse[ERROR_503_TYPES](
                    type="user_not_found",
                    message="Despite valid authorization, you don't seem to exist. Your account may have been deleted.",
                ).model_dump_json(),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Retry-After": "15",
                },
                status_code=503,
            )

        interactive_prompt_meta = await read_interactive_prompt_meta(
            itgs, interactive_prompt_uid=args.interactive_prompt_uid
        )
        if interactive_prompt_meta is None:
            return ERROR_INTERACTIVE_PROMPT_NOT_FOUND_RESPONSE

        display_name = await interactive_prompts.events.helper.get_display_name(
            itgs, auth_result.result
        )

        result = (
            await interactive_prompts.events.helper.create_interactive_prompt_event(
                itgs,
                interactive_prompt_uid=auth_result.result.interactive_prompt_uid,
                user_sub=auth_result.result.user_sub,
                session_uid=args.session_uid,
                event_type="join",
                event_data=NameEventData(name=display_name),
                prompt_time=args.prompt_time,
                prefix_sum_updates=[
                    interactive_prompts.events.helper.PrefixSumUpdate(
                        category="users",
                        amount=1,
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

        await users.lib.stats.on_interactive_prompt_session_started(
            itgs,
            auth_result.result.user_sub,
            user_created_at=user_created_at,
            started_at=result.result.created_at,
        )
        await interactive_prompts.lib.stats.on_interactive_prompt_session_started(
            itgs,
            subcategory=interactive_prompt_meta.journey_subcategory,
            started_at=result.result.created_at,
            user_sub=auth_result.result.user_sub,
        )
        return result.result.response


async def get_user_created_at(itgs: Itgs, *, sub: str) -> Optional[float]:
    res = await get_user_created_at_from_cache(itgs, sub=sub)
    if res is not None:
        return res

    res = await get_user_created_at_from_db(itgs, sub=sub)
    if res is None:
        return None

    await set_user_created_at_in_cache(itgs, sub=sub, created_at=res)
    return res


async def set_user_created_at_in_cache(
    itgs: Itgs, *, sub: str, created_at: float
) -> None:
    cache = await itgs.local_cache()
    cache.set(f"users:{sub}:created_at".encode("utf-8"), value=created_at, expire=86400)


async def get_user_created_at_from_cache(itgs: Itgs, *, sub: str) -> Optional[float]:
    cache = await itgs.local_cache()
    return typing_cast(
        Optional[float], cache.get(f"users:{sub}:created_at".encode("utf-8"))
    )


async def get_user_created_at_from_db(itgs: Itgs, *, sub: str) -> Optional[float]:
    conn = await itgs.conn()
    cursor = conn.cursor("none")

    response = await cursor.execute(
        "SELECT created_at FROM users WHERE sub = ?",
        (sub,),
    )
    if not response.results:
        return None

    return response.results[0][0]
