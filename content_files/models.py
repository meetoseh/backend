from pydantic import BaseModel, Field


class ContentFileRef(BaseModel):
    uid: str = Field(description="The UID of the content file")
    jwt: str = Field(description="The JWT to use to access the content file")
