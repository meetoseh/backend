from typing import List, Literal, Optional, Union

from pydantic import BaseModel, Field


class ClientFlowScreenVariableInputStringFormat(BaseModel):
    type: Literal["string_format"] = Field(description="Discriminatory union field")
    format: str = Field(
        description=(
            "The format string using Python's string format syntax. E.g., `'Hello, {standard[user][name]}'`. "
            "Parameters from the client when triggering the flow are in the `client` dict, "
            "parameters from the server when triggering the flow are in the `server` dict, "
            "and parameters from the standard context are in the `standard` dict. "
        )
    )
    output_path: List[str] = Field(
        description="Where to store the result", min_length=1
    )


class ClientFlowScreenVariableInputCopy(BaseModel):
    type: Literal["copy"] = Field(description="Discriminatory union field")
    input_path: List[str] = Field(
        description="Where to copy the value from. Must start with `client`, `standard`, or `server`, "
        "which tells us which dictionary to take from",
        min_length=1,
    )
    output_path: List[str] = Field(
        description="Where to store the result", min_length=1
    )


ClientFlowScreenVariableInput = Union[
    ClientFlowScreenVariableInputStringFormat, ClientFlowScreenVariableInputCopy
]


class ClientFlowScreenScreen(BaseModel):
    """the `screen` within `ClientFlowScreen`"""

    slug: str = Field(description="The slug of the screen being referenced")
    fixed: dict = Field(
        description="When building the screen input parameters, we start with a clone of this object"
    )
    variable: List[ClientFlowScreenVariableInput] = Field(
        description=(
            "Describes how the flow parameters plus standard context parameters are injected "
            "into the screen input parameters."
        )
    )


class ClientFlowScreen(BaseModel):
    """Describes a screen within the `screens` column of a `client_flows` row. This
    isn't the same thing as a `client_screen`, but a client screen is referenced by
    this object.
    """

    screen: ClientFlowScreenScreen = Field(description="the screen to display")
    name: Optional[str] = Field(
        None,
        description="A hint for the admin area towards the purpose of this screen.",
    )
    allowed_triggers: List[str] = Field(
        description="The slugs of client flows that can be triggered when popping this screen"
    )
