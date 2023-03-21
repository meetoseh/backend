from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal, Optional
from itgs import Itgs
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from interactive_prompts.events.routes.stats import get_users
import time


router = APIRouter()


class ReadJourneyViewsResponse(BaseModel):
    views: int = Field(description="The number of views of the journey")
    retrieved_at: float = Field(
        description="The time at which the views were retrieved"
    )


ERROR_404_TYPES = Literal["not_found"]
NOT_FOUND = Response(
    status_code=404,
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="not_found", message=("There is no journey with that UID")
    ).json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
)


@router.get(
    "/journey_views",
    status_code=200,
    response_model=ReadJourneyViewsResponse,
    responses={
        "404": {
            "description": "There is no journey with that UID",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def read_journey_views(
    journey_uid: str, authorization: Optional[str] = Header(None)
):
    """Fetches the number of views on the journey with the given uid. This endpoint
    generally only requires `O(log(N*M)log(M))` time where N is the number of journeys and M is
    the length of the longest journey lobby, making it suitable for being called frequently.

    Requires standard admin authorization
    """
    async with Itgs() as itgs:
        auth_res = await auth_admin(itgs, authorization)
        if not auth_res.success:
            return auth_res.error_response

        conn = await itgs.conn()
        cursor = conn.cursor("none")

        response = await cursor.execute(
            """
            SELECT
                interactive_prompts.uid
            FROM interactive_prompts
            WHERE
                EXISTS (
                    SELECT 1 FROM journeys
                    WHERE 
                        journeys.uid = ?
                        AND (
                            journeys.interactive_prompt_id = interactive_prompts.id
                            OR (
                                EXISTS (
                                    SELECT 1 FROM interactive_prompt_old_journeys
                                    WHERE interactive_prompt_old_journeys.journey_id = journeys.id
                                        AND interactive_prompt_old_journeys.interactive_prompt_id = interactive_prompts.id
                                )
                            )
                        )
                )
            """,
            (journey_uid,),
        )

        if not response.results:
            return NOT_FOUND

        total_views = 0
        for (interactive_prompt_uid,) in response.results:
            users = await get_users(itgs, interactive_prompt_uid, 0)
            views: int = users["users"]
            total_views += views

        return Response(
            content=ReadJourneyViewsResponse(
                views=total_views, retrieved_at=time.time()
            ).json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=200,
        )
