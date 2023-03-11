import json
from pydantic import BaseModel, Field, constr, validator
from typing import Literal, List, Union


class NumericPrompt(BaseModel):
    """E.g., What's your mood? 1-10"""

    style: Literal["numeric"] = Field(description="The prompt style")
    text: constr(strip_whitespace=True, min_length=1, max_length=75) = Field(
        description="The text to display to the user before they answer"
    )
    min: int = Field(description="The minimum value, inclusive")
    max: int = Field(description="The maximum value, inclusive")
    step: Literal[1] = Field(description="The step size between values")

    @validator("max")
    def max_must_be_gte_than_min(cls, v, values):
        if v < values["min"]:
            raise ValueError("max must be at least min")
        return v

    @validator("step")
    def at_most_10_options(cls, v, values):
        _min = values["min"]
        _max = values["max"]
        step = v

        if (_max - _min) // step > 10:
            raise ValueError("at most 10 options")

        return v

    class Config:
        schema_extra = {
            "example": {
                "style": "numeric",
                "text": "What's your mood?",
                "min": 1,
                "max": 10,
                "step": 1,
            }
        }


class PressPrompt(BaseModel):
    """E.g., press when you like it"""

    style: Literal["press"] = Field(description="The prompt style")
    text: constr(strip_whitespace=True, min_length=1, max_length=75) = Field(
        description="The text to display to the user before they answer"
    )


class ColorPrompt(BaseModel):
    """E.g., what color is this song?"""

    style: Literal["color"] = Field(description="The prompt style")
    text: constr(strip_whitespace=True, min_length=1, max_length=75) = Field(
        description="The text to display to the user before they answer"
    )
    colors: List[str] = Field(
        description="The colors to choose from", min_items=2, max_items=8
    )

    @validator("colors")
    def colors_must_be_hex(cls, v: List[str]):
        for color in v:
            if not color.startswith("#"):
                raise ValueError("colors must be hex codes starting with #")
            if len(color) != 7:
                raise ValueError("colors must be 6 digit hex codes starting with #")
            if not all(c in "0123456789abcdefABCDEF" for c in color[1:]):
                raise ValueError("colors must be hex codes starting with #")
        return [color.upper() for color in v]


class WordPrompt(BaseModel):
    """e.g. what are you feeling?"""

    style: Literal["word"] = Field(description="The prompt style")
    text: constr(strip_whitespace=True, min_length=1, max_length=75) = Field(
        description="The text to display to the user before they answer"
    )
    options: List[constr(min_length=1, max_length=45, strip_whitespace=True)] = Field(
        description="The options to choose from", min_items=2, max_items=8
    )


Prompt = Union[NumericPrompt, PressPrompt, ColorPrompt, WordPrompt]


class PromptWrapper(BaseModel):
    prompt: Prompt = Field()


def parse_prompt_from_json(prompt: str) -> Prompt:
    """Parses a prompt from a JSON string."""
    return PromptWrapper(prompt=json.loads(prompt)).prompt


def is_prompt_swap_trivial(a: Prompt, b: Prompt) -> bool:
    """Determines if the two prompts are functionally equivalent, i.e., they have
    the same style and the same number of options, so the events for the two are
    compatible. An example of a compatible prompt swap is just changing the text,
    or just changing the values of the options (but not the number of options).

    Args:
        a (Prompt): The first prompt
        b (Prompt): The second prompt

    Returns:
        bool: Whether the prompts are compatible
    """
    if a.style == "numeric" and b.style == "numeric":
        return a.min == b.min and a.max == b.max and a.step == b.step

    if a.style == "press" and b.style == "press":
        return True

    if a.style == "color" and b.style == "color":
        return len(a.colors) == len(b.colors)

    if a.style == "word" and b.style == "word":
        return len(a.options) == len(b.options)

    return False
