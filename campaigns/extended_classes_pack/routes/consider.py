from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Optional
from journeys.models.external_journey import ExternalJourney
from models import STANDARD_ERRORS_BY_CODE


router = APIRouter()


class ConsiderExtendedClassesPackRequest(BaseModel):
    emotion: str = Field(description="The emotion word the user selected")


@router.post(
    "/consider",
    status_code=200,
    response_model=ExternalJourney,
    responses={
        "204": {
            "description": "Do not show the extended classes pack offer at this time."
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def consider_extended_classes_pack(
    args: ConsiderExtendedClassesPackRequest,
    authorization: Optional[str] = Header(None),
):
    """Determines if the user should be presented with the extended classes pack
    offer after clicking the given emotion word. This assumes the client is
    already using the inapp notifications module to prevent showing this notification
    multiple times. If this returns 200, then:

    - Display a screen asking if they want to try a 3 minute class
    - If they say no, continue to the normal journey for that emotion
    - If they say yes, call /started, play the returned journey then ask if they want to buy
      the extended classes pack

    Requires standard authorization.
    """
    return Response(status_code=204)
