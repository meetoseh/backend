from typing import List
from pydantic import BaseModel, Field


class ClientFlowDynamicSizeHint(BaseModel):
    """Describes the expected schema for x-dynamic-size on a client screen property"""

    width: List[str] = Field(
        description="The path relative to the root schema to the property containing the width of the image"
    )
    height: List[str] = Field(
        description="The path relative to the root schema to the property containing the height of the image"
    )
