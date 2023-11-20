import time
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    Literal,
    Optional,
    Tuple,
    Protocol,
    TypeVar,
    cast as typing_cast,
)
from fastapi import APIRouter, Header
from fastapi.responses import Response, JSONResponse
from pydantic import BaseModel, Field
from interactive_prompts.models.prompt import Prompt
from itgs import Itgs
from interactive_prompts.auth import auth_any
import interactive_prompts.events.helper as evhelper
from models import (
    STANDARD_ERRORS_BY_CODE,
    AUTHORIZATION_UNKNOWN_TOKEN,
    StandardErrorResponse,
)
import functools
import asyncio

router = APIRouter()


class InteractivePromptStatsResponse(BaseModel):
    prompt_time: float = Field(
        description=(
            "The prompt time these stats incorporate events before. For example, if "
            "the prompt time is 10 seconds, then all events before 10 seconds (which have been "
            "processed) are included in these stats."
        )
    )
    bin_width: float = Field(
        description=(
            "The width of each bin in seconds, for example, if the bin width is 1.5 seconds, then "
            "the first bin has a prompt_time of 1.5 seconds, the second bin has a prompt_time "
            "of 3.0 seconds, and so on."
        )
    )
    users: int = Field(
        description=(
            "How many users are active in the prompt at this point; that is, the number of join "
            "events minus the number of leave events"
        )
    )
    likes: int = Field(
        description=(
            "The number of likes that have been given in the prompt at this point"
        )
    )
    numeric_active: Optional[Dict[int, int]] = Field(
        None,
        description=(
            "If the prompt has a numeric prompt, then this is the number of active "
            "responses by rating. For example, if the prompt has a numeric prompt "
            "with min=3 and max=5, this will have keys [3,4,5] and the values will "
            "be the number of active responses with that rating."
        ),
    )
    press_active: Optional[int] = Field(
        None,
        description=(
            "If the prompt has a press prompt, then this is the number of people pressing "
            "at this point in the prompt. That is, the number of press_prompt_start_response events "
            "minus the numbre of press_prompt_end_response events"
        ),
    )
    press: Optional[int] = Field(
        None,
        description=(
            "If the prompt has a press prompt, the number of presses that "
            "have been given in the prompt at this point, that is, the number "
            "of press_prompt_start_response events."
        ),
    )
    color_active: Optional[List[int]] = Field(
        None,
        description=(
            "If the prompt has a color prompt, then this is the number of active "
            "responses by color. For example, if the prompt has a color prompt "
            "with 3 colors, this is a list of 3 items whose value correspond to "
            "the number of active responses with the color at that index."
        ),
    )
    word_active: Optional[List[int]] = Field(
        None,
        description=(
            "If the prompt has a word prompt, then this is the number of active "
            "responses by word. For example, if the prompt has a word prompt "
            "with 3 words, this is a list of 3 items whose value correspond to "
            "the number of active responses with the word at that index."
        ),
    )


ERROR_404_TYPES = Literal["interactive_prompt_not_found", "bin_not_found"]


@router.get(
    "/stats",
    response_model=InteractivePromptStatsResponse,
    responses={
        "404": {
            "description": "The interactive prompt was not found, or the bin was not found",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def get_interactive_prompt_stats(
    uid: str,
    bin: int,
    authorization: Optional[str] = Header(None),
):
    """Fetches statistics on the given bin for the interactive prompt with the given uid.

    This endpoint requires non-standard authentication: in particular, the
    provided authorization should be a JWT for the interactive prompt with the given uid.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        if uid != auth_result.result.interactive_prompt_uid:
            return AUTHORIZATION_UNKNOWN_TOKEN

        interactive_prompt_meta = await evhelper.get_interactive_prompt_meta(itgs, uid)
        if interactive_prompt_meta is None:
            return Response(
                status_code=404,
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="interactive_prompt_not_found",
                    message=(
                        "Although your authorization was valid, the prompt with "
                        "the given uid was not found: it may have been deleted"
                    ),
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        if bin < 0:
            return JSONResponse(
                status_code=422,
                content={
                    "detail": [
                        {
                            "loc": ["query", "bin"],
                            "msg": "ensure this value is greater than or equal to 0",
                            "type": "value_error.number.not_ge",
                        }
                    ]
                },
            )

        if bin >= interactive_prompt_meta.bins:
            return Response(
                status_code=404,
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="bin_not_found",
                    message=(
                        "The bin you requested was not found; the interactive prompt only has "
                        f"{interactive_prompt_meta.bins} bins"
                    ),
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        parts = await asyncio.gather(
            get_likes(itgs, uid, bin),
            get_users(itgs, uid, bin),
            get_for_prompt(itgs, uid, bin, prompt=interactive_prompt_meta.prompt),
        )

        result = dict()
        for part in parts:
            result.update(part)

        bin_width = (
            interactive_prompt_meta.duration_seconds / interactive_prompt_meta.bins
        )

        return Response(
            InteractivePromptStatsResponse(
                prompt_time=bin * bin_width, bin_width=bin_width, **result
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )


async def get_single_from_tree(itgs: Itgs, uid: str, bin: int, category: str) -> int:
    """Fetches the prefix sum associated with the given bin for the given category
    and a null category value in the interactive prompt with the given uid. This requires log(n)
    rows to be fetched from the database, where n is the number of bins in the
    interactive prompt.
    """

    one_based_index = bin + 1
    indices = []
    while one_based_index > 0:
        indices.append(one_based_index - 1)
        one_based_index -= one_based_index & -one_based_index

    conn = await itgs.conn()
    cursor = conn.cursor("none")

    qmark_list = ",".join(["?"] * len(indices))
    response = await cursor.execute(
        f"""
        SELECT SUM(val) FROM interactive_prompt_event_fenwick_trees
        WHERE
            EXISTS (
                SELECT 1 FROM interactive_prompts
                WHERE interactive_prompts.uid = ?
                  AND interactive_prompts.id = interactive_prompt_event_fenwick_trees.interactive_prompt_id
            )
            AND category = ?
            AND category_value IS NULL
            AND idx IN ({qmark_list})
        """,
        [uid, category, *indices],
    )
    assert response.results is not None, response
    return response.results[0][0] or 0


async def get_by_category_from_tree(
    itgs: Itgs, uid: str, bin: int, category: str
) -> Dict[int, int]:
    """Similar to get_single_from_tree, but the result is broken down by category
    value
    """

    one_based_index = bin + 1
    indices = []
    while one_based_index > 0:
        indices.append(one_based_index - 1)
        one_based_index -= one_based_index & -one_based_index

    conn = await itgs.conn()
    cursor = conn.cursor("none")

    qmark_list = ",".join(["?"] * len(indices))
    response = await cursor.execute(
        f"""
        SELECT category_value, SUM(val) FROM interactive_prompt_event_fenwick_trees
        WHERE
            EXISTS (
                SELECT 1 FROM interactive_prompts
                WHERE interactive_prompts.uid = ?
                  AND interactive_prompts.id = interactive_prompt_event_fenwick_trees.interactive_prompt_id
            )
            AND category = ?
            AND idx IN ({qmark_list})
        GROUP BY category_value
        """,
        [uid, category, *indices],
    )
    assert response.results is not None, response

    result: Dict[int, int] = dict()
    for category_value, val in response.results:
        result[category_value] = val

    return dict(result or [])


class StatsFuncInner(Protocol):
    def __call__(
        self, itgs: Itgs, uid: str, bin: int, *args, **kwargs
    ) -> Awaitable[Dict[str, Any]]:
        ...


TCallable = TypeVar("TCallable", bound=StatsFuncInner)


def stats_func(func: TCallable) -> TCallable:
    """Decorator for functions that fetch stats from the database. This decorator
    will cache the result in memory for a short duration.
    """
    cache_time_seconds: float = 1

    def handler_for_fixed_uid_bin():
        lock = asyncio.Lock()
        cached_value: Optional[Dict[str, Any]] = None
        cached_time: Optional[float] = None
        clear_future: Optional[asyncio.Future] = None

        async def clear_cache() -> None:
            nonlocal cached_value, cached_time, clear_future
            await asyncio.sleep(cache_time_seconds)
            async with lock:
                cached_value = None
                cached_time = None
                clear_future = None

        @functools.wraps(func)
        async def wrapper(
            itgs: Itgs, uid: str, bin: int, *args, **kwargs
        ) -> Dict[str, Any]:
            nonlocal cached_time
            nonlocal cached_value
            nonlocal clear_future
            async with lock:
                now = time.time()
                if (
                    cached_value is None
                    or cached_time is None
                    or now > cached_time + cache_time_seconds
                ):
                    cached_value = await func(itgs, uid, bin, *args, **kwargs)
                    cached_time = now
                    if clear_future is not None:
                        clear_future.cancel()
                    clear_future = asyncio.create_task(clear_cache())
                return cached_value

        return wrapper

    handler_and_cleaner_for_uid_bin: Dict[
        Tuple[str, int], Tuple[Callable, asyncio.Future]
    ] = dict()

    async def cleaner_for_uid_bin(uid: str, bin: int) -> None:
        await asyncio.sleep(cache_time_seconds * 3)
        del handler_and_cleaner_for_uid_bin[(uid, bin)]

    @functools.wraps(func)
    async def general_wrapper(
        itgs: Itgs, uid: str, bin: int, *args, **kwargs
    ) -> Dict[str, Any]:
        key = (uid, bin)
        if key not in handler_and_cleaner_for_uid_bin:
            handler = handler_for_fixed_uid_bin()
            cleaner = asyncio.create_task(cleaner_for_uid_bin(uid, bin))
            handler_and_cleaner_for_uid_bin[key] = (handler, cleaner)
            return await handler(itgs, uid, bin, *args, **kwargs)

        handler, cleaner = handler_and_cleaner_for_uid_bin[key]
        cleaner.cancel()
        cleaner = asyncio.create_task(cleaner_for_uid_bin(uid, bin))
        handler_and_cleaner_for_uid_bin[key] = (handler, cleaner)
        return await handler(itgs, uid, bin, *args, **kwargs)

    return typing_cast(TCallable, general_wrapper)


@stats_func
async def get_users(itgs: Itgs, uid: str, bin: int, *args, **kwargs) -> Dict[str, Any]:
    assert not args
    assert not kwargs
    res = await get_single_from_tree(itgs, uid, bin, "users")
    return {"users": res}


@stats_func
async def get_likes(itgs: Itgs, uid: str, bin: int, *args, **kwargs) -> Dict[str, Any]:
    assert not args
    assert not kwargs
    res = await get_single_from_tree(itgs, uid, bin, "likes")
    return {"likes": res}


@stats_func
async def get_for_prompt(
    itgs: Itgs, uid: str, bin: int, *args, prompt: Prompt, **kwargs
) -> Dict[str, Any]:
    assert not args
    assert not kwargs
    if prompt.style == "numeric":
        return {
            "numeric_active": await get_by_category_from_tree(
                itgs, uid, bin, "numeric_active"
            ),
        }

    if prompt.style == "press":
        press, press_active = await asyncio.gather(
            get_single_from_tree(itgs, uid, bin, "press"),
            get_single_from_tree(itgs, uid, bin, "press_active"),
        )
        return {
            "press": press,
            "press_active": press_active,
        }

    if prompt.style == "color":
        lookup = await get_by_category_from_tree(itgs, uid, bin, "color_active")
        return {
            "color_active": list(lookup.get(i, 0) for i in range(len(prompt.colors)))
        }

    if prompt.style == "word":
        lookup = await get_by_category_from_tree(itgs, uid, bin, "word_active")
        return {
            "word_active": list(lookup.get(i, 0) for i in range(len(prompt.options)))
        }

    raise ValueError(f"Unknown prompt style: {repr(prompt.style)}")
