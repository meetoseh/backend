from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, StringConstraints
from typing import Literal, Optional, Annotated
from auth import auth_admin
from interactive_prompts.lib.read_interactive_prompt_meta import (
    evict_interactive_prompt_meta,
)
from interactive_prompts.lib.read_one_external import evict_interactive_prompt
from journeys.lib.read_one_external import evict_external_journey
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from itgs import Itgs


class UpdateJourneySubcategoryRequest(BaseModel):
    internal_name: Annotated[
        str, StringConstraints(min_length=1, strip_whitespace=True)
    ] = Field(
        description=(
            "The internal name for the journey subcategory, which would generally be "
            "unique, but might not be while we're recategorizing. Statistics for "
            "journeys will be grouped by this name, not the uid"
        )
    )

    external_name: Annotated[
        str, StringConstraints(min_length=1, strip_whitespace=True)
    ] = Field(
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


class UpdateJourneySubcategoryResponse(BaseModel):
    internal_name: str = Field(
        description="The new internal name of the journey subcategory"
    )
    external_name: str = Field(
        description="The new external name of the journey subcategory"
    )
    bias: float = Field(description="The new bias of the journey subcategory")


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
            SET internal_name = ?, external_name = ?, bias = ?
            WHERE
                uid = ?
            """,
            (args.internal_name, args.external_name, args.bias, uid),
        )
        if response.rows_affected is None or response.rows_affected < 1:
            return Response(
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="journey_subcategory_not_found",
                    message="The journey subcategory with that uid was not found, it may have been deleted",
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=404,
            )

        biggest_journey_id = 0
        while True:
            response = await cursor.execute(
                """
                SELECT
                    journeys.id, journeys.uid, interactive_prompts.uid
                FROM journeys
                JOIN interactive_prompts ON interactive_prompts.id = journeys.interactive_prompt_id
                WHERE
                    EXISTS (
                        SELECT 1 FROM journey_subcategories
                        WHERE journey_subcategories.id = journeys.journey_subcategory_id
                          AND journey_subcategories.uid = ?
                    )
                    AND journeys.id > ?
                    AND journeys.deleted_at IS NULL
                ORDER BY journeys.id ASC
                LIMIT 100
                """,
                (
                    uid,
                    biggest_journey_id,
                ),
            )
            if not response.results:
                break

            for (
                _,
                journey_uid,
                interactive_prompt_uid,
            ) in response.results:
                await evict_external_journey(itgs, uid=journey_uid)
                await evict_interactive_prompt(
                    itgs, interactive_prompt_uid=interactive_prompt_uid
                )
                await evict_interactive_prompt_meta(
                    itgs, interactive_prompt_uid=interactive_prompt_uid
                )

            biggest_journey_id = response.results[-1][0]

        return Response(
            content=UpdateJourneySubcategoryResponse(
                internal_name=args.internal_name,
                external_name=args.external_name,
                bias=args.bias,
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=200,
        )
