from dataclasses import dataclass
import math
from interactive_prompts.lib.read_one_external import read_interactive_prompt_meta
from interactive_prompts.models.prompt import Prompt
from functools import lru_cache

from itgs import Itgs


@dataclass
class InteractivePromptAugmentedMeta:
    """Carries over the information from read_interactive_prompt_meta, but adds
    some additional information that is useful for events-related endpoints. This
    information doesn't require any database queries.
    """

    uid: str
    """The uid of the interactive prompt"""
    prompt: Prompt
    """Information about the prompt"""
    duration_seconds: int
    """The duration of the interactive prompt in seconds"""
    bins: int
    """How many bins are used in the fenwick tree"""


@lru_cache(maxsize=128)
def compute_bins(duration_seconds: int) -> int:
    if duration_seconds <= 1:
        return 1
    else:
        return 2 ** math.ceil(math.log2(duration_seconds)) - 1


async def get_interactive_prompt_meta(
    itgs: Itgs, uid: str
) -> InteractivePromptAugmentedMeta:
    """Reads the interactive prompt meta for the interactive prompt with the given
    uid. This will fetch from the nearest available source, filling intermediary
    caches as it goes.

    Args:
        itgs (Itgs): The integrations to use to connect to networked services
        uid (str): The uid of the interactive prompt

    Returns:
        InteractivePromptAugmentedMeta: The interactive prompt meta
    """
    meta = await read_interactive_prompt_meta(itgs, interactive_prompt_uid=uid)
    return InteractivePromptAugmentedMeta(
        uid=uid,
        prompt=meta.prompt,
        duration_seconds=meta.duration_seconds,
        bins=compute_bins(meta.duration_seconds),
    )
