from fastapi import APIRouter, Header
from fastapi.responses import Response
from typing import Annotated, Optional
from pydantic import BaseModel, Field
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE
from itgs import Itgs
import emails.auth


router = APIRouter()


class AuthorizeTemplatingRequest(BaseModel):
    template_slug: str = Field(
        description="The template slug to authorize access to",
    )


class AuthorizeTemplatingResponse(BaseModel):
    jwt: str = Field(
        description="The JWT to use to template the email",
    )


@router.post(
    "/authorize_templating",
    response_model=AuthorizeTemplatingResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def authorize_templating(
    args: AuthorizeTemplatingRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """
    Produces authorization for accessing the email-templates server, which can
    produce the HTML content for an email template (/api/3/docs). The provided
    authorization is only valid for a limited time, and will only work for the
    specified email template.

    This is primarily intended for previewing emails in admin

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        jwt = await emails.auth.create_jwt(itgs, args.template_slug)
        return Response(
            content=AuthorizeTemplatingResponse.__pydantic_serializer__.to_json(
                AuthorizeTemplatingResponse(jwt=jwt)
            ),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=200,
        )
