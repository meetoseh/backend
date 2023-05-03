from typing import Literal, Optional, Union
from pydantic import BaseModel, Field


class JourneyEmotionCreationHintManual(BaseModel):
    type: Literal["manual"] = Field(description="The type of creation hint")
    user_sub: str = Field(description="The sub of the user who attached this emotion")


class JourneyEmotionCreationHintAI(BaseModel):
    type: Literal["ai"] = Field(description="The type of creation hint")
    model: str = Field(description="The model that created this emotion")
    prompt_version: str = Field(
        description="The version of the prompt provided to the model, formatted like semver"
    )


JourneyEmotionCreationHint = Union[
    JourneyEmotionCreationHintManual, JourneyEmotionCreationHintAI
]


class JourneyEmotion(BaseModel):
    uid: str = Field(description="The UID of the journey <-> emotion relationship")
    journey_uid: str = Field(
        description="The UID of the journey that this emotion is attached to"
    )
    emotion: str = Field(description="The emotion word that is attached to the journey")
    creation_hint: Optional[JourneyEmotionCreationHint] = Field(
        description="Provides insight into how the emotion was attached to the journey"
    )
    created_at: float = Field(
        description="When the emotion was attached to the journey, in seconds since the unix epoch"
    )
