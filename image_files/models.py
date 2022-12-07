from pydantic import BaseModel, Field


class ImageFileRef(BaseModel):
    uid: str = Field(description="The UID of the image file")
    jwt: str = Field(description="The JWT to use to access the image file")
