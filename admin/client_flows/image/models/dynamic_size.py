from pydantic import BaseModel, Field


class ClientFlowDynamicSize(BaseModel):
    """Whats computed using a ClientFlowDynamicSizeHint within a schema when combined with the
    actual data
    """

    width: int = Field(description="The logical width of the image, i.e., the 1x width")
    height: int = Field(
        description="The logical height of the image, i.e., the 1x height"
    )
