from pydantic import BaseModel, Field


class TranscriptRef(BaseModel):
    uid: str = Field(description="The UID of the transcript file")
    jwt: str = Field(
        description="A token which provides access to the transcript with the given uid"
    )
