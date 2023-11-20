from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, StringConstraints
from typing import Literal, Optional, Annotated
from auth import auth_any
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from itgs import Itgs


router = APIRouter()


class UpdateNameArgs(BaseModel):
    given_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
    ] = Field(description="the new given name")
    family_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
    ] = Field(description="the new family name")


class UpdateNameResponse(BaseModel):
    given_name: str = Field(description="the new given name")
    family_name: str = Field(description="the new family name")


ERROR_503_TYPES = Literal["integrity"]


@router.post(
    "/attributes/name",
    response_model=UpdateNameResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def update_name(
    args: UpdateNameArgs, authorization: Optional[str] = Header(None)
):
    """Updates the authorized users name. The args may be cleaned up before being returned.

    Requires standard authorization.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor("none")
        response = await cursor.execute(
            "UPDATE users SET given_name=?, family_name=? WHERE sub=?",
            (args.given_name, args.family_name, auth_result.result.sub),
        )
        if response.rows_affected is None or response.rows_affected < 1:
            return Response(
                content=StandardErrorResponse[ERROR_503_TYPES](
                    type="integrity",
                    message="Another update occurred while this request was being processed. Please try again.",
                ).model_dump_json(),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Retry-After": "5",
                },
                status_code=503,
            )

        jobs = await itgs.jobs()
        await jobs.enqueue(
            "runners.revenue_cat.ensure_user", user_sub=auth_result.result.sub
        )
        return UpdateNameResponse(
            given_name=args.given_name, family_name=args.family_name
        )
