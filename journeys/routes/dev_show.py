from fastapi.responses import JSONResponse
from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import Any, Dict, Literal
from itgs import Itgs
from models import (
    AUTHORIZATION_UNKNOWN_TOKEN,
    STANDARD_ERRORS_BY_CODE,
    StandardErrorResponse,
)
import journeys.auth
import journeys.events.helper as evhelper
import os

router = APIRouter()


class DevShowJourneyResponse(BaseModel):
    uid: str = Field(description="The UID of the journey")
    jwt: str = Field(description="The JWT to use to access the journey")
    lobby_duration_seconds: float = Field(
        description="The duration of the lobby, in seconds"
    )
    fenwick_bin_width: float = Field(
        description="The width of the Fenwick bins, for stats, in seconds"
    )
    prompt: Dict[str, Any] = Field(description="The prompt information for the journey")


ERROR_404_TYPE = Literal["not_found"]


@router.get(
    "/dev_show/{uid}",
    response_model=DevShowJourneyResponse,
    responses={
        "404": {
            "description": "there is no journey with that uid",
            "model": StandardErrorResponse[ERROR_404_TYPE],
        },
        "403": STANDARD_ERRORS_BY_CODE["403"],
    },
)
async def dev_show_journey(uid: str):
    """Returns a reference to the journey with the given uid. Note that under normal
    circumstances an endpoint which returns a journey ref would also create and return
    a session uid, however, this operation is split for development via the dev_start_session
    endpoint. This endpoint only works in development."""
    if os.environ["ENVIRONMENT"] != "dev":
        return AUTHORIZATION_UNKNOWN_TOKEN

    async with Itgs() as itgs:
        meta = await evhelper.get_journey_meta(itgs, uid)
        if meta is None:
            return JSONResponse(
                content=StandardErrorResponse[ERROR_404_TYPE](
                    type="not_found", message="There is no journey with that uid"
                ).dict(),
                status_code=404,
            )

        jwt = await journeys.auth.create_jwt(itgs, uid)
        return JSONResponse(
            content=DevShowJourneyResponse(
                uid=uid,
                jwt=jwt,
                fenwick_bin_width=meta.lobby_duration_seconds / meta.bins,
                lobby_duration_seconds=meta.lobby_duration_seconds,
                histogram_bin_width=1.0,
                prompt=meta.prompt,
            ).dict(),
            status_code=200,
        )
