from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, StringConstraints
from typing import Annotated, Literal, Optional
from auth import auth_any
from itgs import Itgs
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse


router = APIRouter()


class CheckIfShareableRequest(BaseModel):
    uid: Annotated[str, StringConstraints(min_length=2, max_length=255)] = Field(
        description="The UID of the journey"
    )


class CheckIfShareableResponse(BaseModel):
    shareable: bool = Field(description="Whether the journey is shareable")


ERROR_404_TYPES = Literal["not_found"]
ERROR_NOT_FOUND_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_404_TYPES].__pydantic_serializer__.to_json(
        StandardErrorResponse[ERROR_404_TYPES](
            type="not_found",
            message="There is no journey with that uid",
        )
    ),
    status_code=404,
    headers={"Content-Type": "application/json; charset=utf-8"},
)


@router.post(
    "/check_if_shareable",
    response_model=CheckIfShareableResponse,
    responses={
        **STANDARD_ERRORS_BY_CODE,
        "404": {
            "description": "The journey with the given uid does not exist",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
    },
)
async def check_if_shareable(
    args: CheckIfShareableRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Checks if the journey with the given uid is shareable by the given
    authorized user.

    Requires standard authorization.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor("none")

        response = await cursor.execute(
            """
            SELECT
                (
                    journeys.special_category IS NULL
                    AND NOT EXISTS (
                        SELECT 1 FROM course_journeys 
                        WHERE course_journeys.journey_id = journeys.id
                    )
                ) AS b1
            FROM journeys
            WHERE
                journeys.uid = ?
                AND journeys.deleted_at IS NULL
            """,
            (args.uid,),
        )

        if not response.results:
            return ERROR_NOT_FOUND_RESPONSE

        shareable = bool(response.results[0][0])
        return Response(
            content=CheckIfShareableResponse.__pydantic_serializer__.to_json(
                CheckIfShareableResponse(shareable=shareable)
            ),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "private, max-age=86400",
            },
            status_code=200,
        )
