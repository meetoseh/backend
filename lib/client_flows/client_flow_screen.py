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


class ClientFlowScreenVariableInputExtract(BaseModel):
    type: Literal["extract"] = Field(description="Discriminatory union field")
    input_path: List[str] = Field(
        description=(
            "A path to the value to extract. Must start with `server`. The target path "
            "must match a schema object with type string whose format is either "
            "`course_uid` or `journey_uid`. That will be converted to an ExternalCourse "
            "or ExternalJourney, respectively, and then used as the target for the "
            "extracted_path"
        ),
        min_length=2,
    )
    extracted_path: List[str] = Field(
        description="The path within the extracted object to take from", min_length=1
    )
    output_path: List[str] = Field(
        description="Where to store the result", min_length=1
    )
    skip_if_missing: bool = Field(
        False,
        description=(
            "If True, we will skip the entire screen at trigger time if the extraction "
            "path is null in the converted object. If False, we will provide null."
        ),
    )


ClientFlowScreenVariableInput = Union[
    ClientFlowScreenVariableInputStringFormat,
    ClientFlowScreenVariableInputCopy,
    ClientFlowScreenVariableInputExtract,
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
