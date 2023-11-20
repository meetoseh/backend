from fastapi import APIRouter, Header
from fastapi.responses import Response
from typing import Literal, Optional
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from itgs import Itgs


ERROR_404_TYPES = Literal["journey_subcategory_not_found"]
ERROR_409_TYPES = Literal["journey_uses_subcategory"]


router = APIRouter()


@router.delete(
    "/{uid}",
    status_code=204,
    responses={
        "404": {
            "description": "The journey subcategory was not found",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        "409": {
            "description": "The journey subcategory is in use",
            "model": StandardErrorResponse[ERROR_409_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def delete_journey_subcategory(
    uid: str, authorization: Optional[str] = Header(None)
):
    """Deletes the journey subcategory with the given uid, if it exists and is not in use.

    This requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor("weak")

        response = await cursor.execute(
            """
            DELETE FROM journey_subcategories
            WHERE
                journey_subcategories.uid = ?
                AND NOT EXISTS (
                    SELECT 1 FROM journeys
                    WHERE journeys.journey_subcategory_id = journey_subcategories.id
                )
            """,
            (uid,),
        )
        if response.rows_affected is not None and response.rows_affected > 0:
            return Response(status_code=204)

        response = await cursor.execute(
            """
            SELECT
                journeys.uid,
                journeys.title
            FROM journeys
            WHERE
                EXISTS (
                    SELECT 1 FROM journey_subcategories
                    WHERE journey_subcategories.id = journeys.journey_subcategory_id
                      AND journey_subcategories.uid = ?
                )
            ORDER BY journeys.uid ASC
            LIMIT 10
            """,
            (uid,),
        )
        if response.results:
            return Response(
                content=StandardErrorResponse[ERROR_409_TYPES](
                    type="journey_uses_subcategory",
                    message=(
                        "The journey subcategory is in use by, at least, the following journeys: "
                        + ", ".join(
                            [f"{title} ({uid})" for uid, title in response.results]
                        )
                    ),
                    markdown=(
                        "The journey subcategory is in use by, at least, the following journeys:\n"
                        + "\n".join(
                            [
                                f"- [{title}](/admin/journeys/{uid})"
                                for uid, title in response.results
                            ]
                        )
                    ),
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=409,
            )

        return Response(
            content=StandardErrorResponse[ERROR_404_TYPES](
                type="journey_subcategory_not_found",
                message="The journey subcategory with that uid was not found, it may have been deleted",
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=404,
        )
