import secrets
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, constr
from typing import Literal, Optional
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from itgs import Itgs


class UpdateJourneySubcategoryRequest(BaseModel):
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


class UpdateJourneySubcategoryResponse(BaseModel):
    internal_name: str = Field(
        description="The new internal name of the journey subcategory"
    )
    external_name: str = Field(
        description="The new external name of the journey subcategory"
    )


ERROR_404_TYPES = Literal["journey_subcategory_not_found"]


router = APIRouter()


@router.put(
    "/{uid}",
    status_code=200,
    response_model=UpdateJourneySubcategoryResponse,
    responses={
        "404": {
            "description": "The journey subcategory was not found",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def update_journey_subcategory(
    uid: str,
    args: UpdateJourneySubcategoryRequest,
    authorization: Optional[str] = Header(None),
):
    """Updates a journey subcategory with the given uid.

    This uses standard authorization and requires an admin account.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor("none")

        response = await cursor.execute(
            """
            UPDATE journey_subcategories
            SET internal_name = ?, external_name = ?
            WHERE
                uid = ?
            """,
            (args.internal_name, args.external_name, uid),
        )
        if response.rows_affected is None or response.rows_affected < 1:
            return Response(
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="journey_subcategory_not_found",
                    message="The journey subcategory with that uid was not found, it may have been deleted",
                ).json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=404,
            )

        return Response(
            content=UpdateJourneySubcategoryResponse(
                internal_name=args.internal_name,
                external_name=args.external_name,
            ).json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=200,
        )
