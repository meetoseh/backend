import json
from typing import Literal, NoReturn, Optional, cast as typing_cast
from pydantic import BaseModel, Field
from error_middleware import handle_error
from interactive_prompts.models.prompt import Prompt
from itgs import Itgs
import perpetual_pub_sub as pps


class InteractivePromptMeta(BaseModel):
    """The meta information about an interactive prompt that we store for
    internal use
    """

    uid: str = Field(description="The uid of the interactive prompt")
    prompt: Prompt = Field(description="Information on the prompt itself")
    duration_seconds: int = Field(
        description="The duration of the interactive prompt in seconds"
    )
    journey_subcategory: Optional[str] = Field(
        description=(
            "If the interactive prompt is for a journey, this is the subcategory of the "
            "journey. Otherwise, this is None."
        )
    )


async def read_interactive_prompt_meta(
    itgs: Itgs, *, interactive_prompt_uid: str
) -> Optional[InteractivePromptMeta]:
    """Fetches cached meta information about the interactive prompt with the given
    uid, if it can be found anywhere, otherwise returns None

    Args:
        itgs (Itgs): The integrations to (re)use
        interactive_prompt_uid (str): The UID of the interactive prompt to fetch

    Returns:
        The interactive prompt meta, or None if it is not available anywhere
            because there is no interactive prompt with that uid.
    """
    locally_cached = await read_interactive_prompt_meta_from_cache(
        itgs, interactive_prompt_uid=interactive_prompt_uid
    )
    if locally_cached is not None:
        return locally_cached

    db_value = await read_interactive_prompt_meta_from_db(
        itgs, interactive_prompt_uid=interactive_prompt_uid
    )
    if db_value is None:
        return None

    await write_interactive_prompt_meta_to_cache(
        itgs, interactive_prompt_uid=interactive_prompt_uid, meta=db_value
    )
    return db_value


async def read_interactive_prompt_meta_from_cache(
    itgs: Itgs, *, interactive_prompt_uid: str
) -> Optional[InteractivePromptMeta]:
    """Reads the cached meta information on the interactive prompt with the
    given uid, if it exists, otherwise returns None

    Args:
        itgs (Itgs): The integrations to (re)use
        interactive_prompt_uid (str): The UID of the interactive prompt to fetch

    Returns:
        The interactive prompt meta, or None if it is not available anywhere
            because there is no interactive prompt with that uid.
    """
    cache = await itgs.local_cache()
    raw = typing_cast(
        Optional[bytes],
        cache.get(f"interactive_prompts:{interactive_prompt_uid}:meta".encode("utf-8")),
    )
    if raw is None:
        return None
    return InteractivePromptMeta.model_validate_json(raw)


async def write_interactive_prompt_meta_to_cache(
    itgs: Itgs, *, interactive_prompt_uid: str, meta: InteractivePromptMeta
) -> None:
    """Writes the given meta information to the cache

    Args:
        itgs (Itgs): The integrations to (re)use
        interactive_prompt_uid (str): The UID of the interactive prompt to write
        meta (InteractivePromptMeta): The meta information to write
    """
    cache = await itgs.local_cache()
    cache.set(
        f"interactive_prompts:{interactive_prompt_uid}:meta".encode("utf-8"),
        meta.model_dump_json().encode("utf-8"),
        tag="collab",
        expire=86400,
    )


async def read_interactive_prompt_meta_from_db(
    itgs: Itgs,
    *,
    interactive_prompt_uid: str,
    consistency: Literal["none", "weak", "strong"] = "none",
) -> Optional[InteractivePromptMeta]:
    """Reads the meta information on the interactive prompt with the
    given uid, if it exists, from the database, otherwise returns None

    Args:
        itgs (Itgs): The integrations to (re)use
        interactive_prompt_uid (str): The UID of the interactive prompt to fetch
        consistency ('none', 'weak', 'strong'): The consistency level to use; if 'none'
            failures will be retried with 'weak'.

    Returns:
        The interactive prompt meta, or None if it is not available anywhere
            because there is no interactive prompt with that uid.
    """
    conn = await itgs.conn()
    cursor = conn.cursor(consistency)

    response = await cursor.execute(
        """
        SELECT
            interactive_prompts.uid,
            interactive_prompts.prompt,
            interactive_prompts.duration_seconds,
            journey_subcategories.internal_name
        FROM interactive_prompts
        LEFT OUTER JOIN journey_subcategories ON (
            EXISTS (
                SELECT 1 FROM journeys
                WHERE journeys.interactive_prompt_id = interactive_prompts.id
                  AND journeys.journey_subcategory_id = journey_subcategories.id
            )
        )
        WHERE interactive_prompts.uid = ?
        """,
        (interactive_prompt_uid,),
    )
    if not response.results:
        if consistency == "none":
            return await read_interactive_prompt_meta_from_db(
                itgs, interactive_prompt_uid=interactive_prompt_uid, consistency="weak"
            )
        return None

    return InteractivePromptMeta(
        uid=response.results[0][0],
        prompt=json.loads(response.results[0][1]),
        duration_seconds=response.results[0][2],
        journey_subcategory=response.results[0][3],
    )


async def evict_interactive_prompt_meta(
    itgs: Itgs, *, interactive_prompt_uid: str
) -> None:
    """Evicts the interactive prompt meta for the given uid from all instances
    caches.

    Args:
        itgs (Itgs): The integrations to (re)use
        interactive_prompt_uid (str): The UID of the interactive prompt to evict
    """
    redis = await itgs.redis()
    redis.publish(
        b"ps:interactive_prompts:meta:push_cache",
        interactive_prompt_uid.encode("utf-8"),
    )


async def cache_push_loop() -> NoReturn:
    """Uses the perpetual pub sub to listen for any interactive prompts whose
    meta information should be evicted from the cache
    """
    assert pps.instance is not None
    try:
        async with pps.PPSSubscription(
            pps.instance, "ps:interactive_prompts:meta:push_cache", "ipm-cpl"
        ) as sub:
            async for raw_message_bytes in sub:
                interactive_prompt_uid = raw_message_bytes.decode("utf-8")

                async with Itgs() as itgs:
                    local_cache = await itgs.local_cache()
                    local_cache.delete(
                        f"interactive_prompts:{interactive_prompt_uid}:meta".encode(
                            "utf-8"
                        )
                    )
    except Exception as e:
        if pps.instance.exit_event.is_set() and isinstance(e, pps.PPSShutdownException):
            return  # type: ignore
        await handle_error(e)
    finally:
        print(
            "interactive_prompts read_interactive_prompt_meta cache_push_loop exiting"
        )
