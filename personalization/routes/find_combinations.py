from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import List, Optional
from models import STANDARD_ERRORS_BY_CODE
from auth import auth_admin
from itgs import Itgs
from personalization.lib.s01_find_combinations import get_instructor_category_and_biases
import time


router = APIRouter()


class Instructor(BaseModel):
    uid: str = Field(
        description="The primary stable unique identifier of the instructor"
    )
    name: str = Field(description="The name of the instructor")
    bias: float = Field(description="The bias for the instructor")


class Category(BaseModel):
    uid: str = Field(description="The primary stable unique identifier of the category")
    internal_name: str = Field(description="The internal name of the category")
    bias: float = Field(description="The bias for the category")


class Combination(BaseModel):
    instructor: Instructor = Field(description="The instructor of the combination")
    category: Category = Field(description="The category of the combination")


class FindCombinationsResponse(BaseModel):
    combinations: List[Combination] = Field(
        description="The combinations found for the given emotion"
    )
    computation_time: float = Field(
        description="The time it took to fetch the combinations, in fractional seconds"
    )


@router.get(
    "/combinations",
    responses=STANDARD_ERRORS_BY_CODE,
    response_model=FindCombinationsResponse,
)
async def find_combinations(emotion: str, authorization: Optional[str] = Header(None)):
    """Determines what instructor/category combinations are available
    for the given emotion. This is a debugging endpoint corresponding to
    the first step when selecting which journey to offer a user based on
    the emotion they selected.

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        started_at = time.perf_counter()
        items = await get_instructor_category_and_biases(itgs, emotion=emotion)
        computation_time = time.perf_counter() - started_at

        return Response(
            content=FindCombinationsResponse(
                combinations=[
                    Combination(
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
                    )
                    for raw in items
                ],
                computation_time=computation_time,
            ).json(),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "private, max-age=60, stale-while-revalidate=60, stale-if-error=86400",
            },
        )
