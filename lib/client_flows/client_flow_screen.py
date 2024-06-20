from typing import List, Literal, Optional, Union
from enum import IntFlag, auto
from pydantic import BaseModel, Field

from visitors.lib.get_or_create_visitor import VisitorSource


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


class ClientFlowScreenFlag(IntFlag):
    """We include a int64 on client flow screens which functions as a bit-field,
    where set bits do not change behavior and unset bits prevent the screen
    from being shown in the corresponding context.
    """

    SHOWS_ON_IOS = auto()
    """If unset, this screen should be skipped at peek time on the iOS platform"""

    SHOWS_ON_ANDROID = auto()
    """If unset, this screen should be skipped at peek time on the Android platform"""

    SHOWS_ON_WEB = auto()
    """If unset, this screen should be skipped at peek time on the web platform"""

    SHOWS_FOR_FREE = auto()
    """If unset, this screen should be skipped at peek time for free users"""

    SHOWS_FOR_PRO = auto()
    """If unset, this screen should be skipped at peek time for Oseh+ users"""


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
    flags: int = Field(
        description="A bit-field that suppresses this screen in certain contexts"
    )


def get_flow_screen_flag_by_platform(platform: VisitorSource) -> ClientFlowScreenFlag:
    """Returns the corresponding flag for the given platform"""
    if platform == "ios":
        return ClientFlowScreenFlag.SHOWS_ON_IOS
    elif platform == "android":
        return ClientFlowScreenFlag.SHOWS_ON_ANDROID
    elif platform == "browser":
        return ClientFlowScreenFlag.SHOWS_ON_WEB
    else:
        raise ValueError(f"Unknown platform: {platform}")
