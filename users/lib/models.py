from pydantic import BaseModel, Field
from typing import Optional
from image_files.models import ImageFileRef


class User(BaseModel):
    """A user as is returned from the admin endpoints for listing / updating
    users. We don't include many sub-fields such as where they came from as it would
    quickly bloat this model into uselessness, but that does mean we need a lot
    of endpoints and requests to get everything about a user.
    """

    sub: str = Field(
        description="The primary unique identifier for users, which is the subject of their JWTs"
    )
    email: str = Field(
        description="The user's primary email address. Not necessarily unique"
    )
    email_verified: bool = Field(
        description=(
            "True if we are fairly sure this user actually owns this email, false "
            "if we have no reason to believe that's the case"
        )
    )
    phone_number: Optional[str] = Field(
        description=(
            "The users primary phone number, if known, not necessarily unique."
        )
    )
    phone_number_verified: Optional[bool] = Field(
        description=(
            "True if we are fairly sure this user actually owns this phone number, "
            "false if we have no reason to believe that's the case"
        )
    )
    given_name: Optional[str] = Field(description="The user's first name")
    family_name: Optional[str] = Field(description="The user's last name")
    admin: bool = Field(description="Whether or not the user is an admin")
    revenue_cat_id: str = Field(
        description="The ID of this user on revenuecat, for purchase history"
    )
    profile_picture: Optional[ImageFileRef] = Field(
        description="The users profile picture, if they have one"
    )
    created_at: float = Field(
        description="The time at which this user was created, in seconds since the epoch"
    )
    last_seen_at: float = Field(
        description="The last time we saw this user, in seconds since the epoch"
    )
