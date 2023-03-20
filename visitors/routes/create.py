from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal
from itgs import Itgs
import time

from visitors.lib.get_or_create_visitor import (
    VisitorSource,
    get_or_create_unsanitized_visitor,
)


router = APIRouter()


class CreateVisitorResponse(BaseModel):
    uid: str = Field(
        description="The unique identifier to use in future requests to identify this visitor"
    )


@router.post("/", status_code=201, response_model=CreateVisitorResponse)
async def create_visitor(source: VisitorSource):
    """Creates a new visitor, which can be used to associate basic attribution
    data across requests. The source describes which client the visitor is for.
    """
    async with Itgs() as itgs:
        uid = await get_or_create_unsanitized_visitor(
            itgs, visitor=None, source=source, seen_at=time.time()
        )

        return Response(
            content=CreateVisitorResponse(uid=uid).json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=201,
        )
