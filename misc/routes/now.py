from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel, Field
import time

router = APIRouter()


class NowResponse(BaseModel):
    now: float = Field(
        description="The current server time in unix seconds since the unix epoch."
    )


@router.get("/now", response_model=NowResponse)
async def now():
    """Gets the current server time for use with handling client-side clock drift.
    Generally the client should use https://en.wikipedia.org/wiki/Cristian%27s_algorithm
    to compare server-side times, e.g, JWT expirations, as some clients are known to
    have significant (1 hour+) clock-drift.
    """
    return Response(
        content=NowResponse.__pydantic_serializer__.to_json(
            NowResponse(now=time.time())
        ),
        headers={"Content-Type": "application/json; charset=utf-8"},
        status_code=200,
    )
