from typing import List
from pydantic import BaseModel, Field


class PeekedScreenItem(BaseModel):
    slug: str = Field(description="The slug of the screen")
    parameters: dict = Field(
        description="The parameters for the screen, which meet the screens schema"
    )


class PeekedScreen(BaseModel):
    active: PeekedScreenItem = Field(
        description="The head of the queue, ie., the screen to actually show now"
    )
    active_jwt: str = Field(
        description="The JWT which can be used to pop or trace to the active screen"
    )
    prefetch: List[PeekedScreenItem] = Field(
        description=(
            "The screens which might be coming next and the client MAY start "
            "loading resources for. These are not necessarily in the order they "
            "will be shown, and there is no guarrantee that they will be shown at all. "
            "Note that any JWTs in this list will be refreshed on every peek"
        )
    )


class PeekScreenResponse(BaseModel):
    visitor: str = Field(description="The new visitor UID to use")
    screen: PeekedScreen = Field(description="The screen to show or skip")
