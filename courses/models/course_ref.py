from pydantic import BaseModel, Field


class CourseRef(BaseModel):
    """Provides access to a course disconnected from a user"""

    uid: str = Field(description="The course that you have access to")
    jwt: str = Field(description="The JWT that provides access to that course")
