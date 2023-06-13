import secrets
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, constr
from typing import Optional
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE
from itgs import Itgs


class CreateJourneySubcategoryRequest(BaseModel):
    internal_name: constr(min_length=1, strip_whitespace=True) = Field(
        description=(
            "The internal name for the journey subcategory, which would generally be "
            "unique, but might not be while we're recategorizing. Statistics for "
            "journeys will be grouped by this name, not the uid"
        )
    )

    external_name: constr(min_length=1, strip_whitespace=True) = Field(
        description=(
            "The external name for the journey subcategory, which is shown on "
            "the experience screen"
        )
    )

    bias: float = Field(
        description=(
            "A non-negative number generally less than 1 that influences "
            "content selection towards this journey subcategory."
        ),
        ge=0,
    )


class CreateJourneySubcategoryResponse(BaseModel):
    uid: str = Field(description="The uid of the journey subcategory")
    internal_name: str = Field(
        description="The internal name of the journey subcategory"
    )
    external_name: str = Field(
        description="The external name of the journey subcategory"
    )
    bias: float = Field(description="The bias of the journey subcategory")


router = APIRouter()


@router.post(
    "/",
    status_code=201,
    response_model=CreateJourneySubcategoryResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def create_journey_subcategory(
    args: CreateJourneySubcategoryRequest, authorization: Optional[str] = Header(None)
):
    """Creates a new journey subcategory with the given internal and external names.

    This uses standard authorization and requires an admin account.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor("none")

        uid = f"oseh_jsc_{secrets.token_urlsafe(16)}"

        await cursor.execute(
            "INSERT INTO journey_subcategories (uid, internal_name, external_name, bias) VALUES (?, ?, ?, ?)",
            (uid, args.internal_name, args.external_name, args.bias),
        )
        return Response(
            content=CreateJourneySubcategoryResponse(
                uid=uid,
                internal_name=args.internal_name,
                external_name=args.external_name,
                bias=args.bias,
            ).json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=201,
        )
