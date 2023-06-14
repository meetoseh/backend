from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import List, Optional
from models import STANDARD_ERRORS_BY_CODE
from personalization.routes.find_combinations import Instructor, Category
from personalization.lib.s01_find_combinations import get_instructor_category_and_biases
from personalization.lib.s02_lowest_view_count import map_to_lowest_view_counts
from auth import auth_admin
from itgs import Itgs
import time


router = APIRouter()


class LowestViewCountRow(BaseModel):
    instructor: Instructor
    category: Category
    view_count: int = Field(
        description="The minimum view count for the given instructor and category"
    )


class FindLowestViewCountsResponse(BaseModel):
    rows: List[LowestViewCountRow] = Field(
        description="The rows found for the given emotion"
    )
    computation_time: float = Field(
        description="The time it took to complete the second step, in fractional seconds"
    )


@router.get(
    "/lowest_view_counts",
    responses=STANDARD_ERRORS_BY_CODE,
    response_model=FindLowestViewCountsResponse,
)
async def find_lowest_view_counts(
    emotion: str, user_sub: str, authorization: Optional[str] = Header(None)
):
    """Performs the first step of the algorithm for finding what
    instructor/category combinations are available for the given emotion, then
    maps those to the lowest view count by the user with the given sub. This is
    a debugging endpoint corresponding to the second step of the personalization
    algorithm, where the lowest view counts are fetched in anticipation of step
    5.

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        combinations = await get_instructor_category_and_biases(itgs, emotion=emotion)
        started_at = time.perf_counter()
        view_counts = await map_to_lowest_view_counts(
            itgs, combinations=combinations, user_sub=user_sub, emotion=emotion
        )
        computation_time = time.perf_counter() - started_at

        return Response(
            content=FindLowestViewCountsResponse(
                rows=[
                    LowestViewCountRow(
                        instructor=Instructor(
                            uid=raw.instructor_uid,
                            name=raw.instructor_name,
                            bias=raw.instructor_bias,
                        ),
                        category=Category(
                            uid=raw.category_uid,
                            internal_name=raw.category_internal_name,
                            bias=raw.category_bias,
                        ),
                        view_count=view_count,
                    )
                    for raw, view_count in zip(combinations, view_counts)
                ],
                computation_time=computation_time,
            ).json(),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "private, max-age=60, stale-while-revalidate=60, stale-if-error=86400",
            },
        )
