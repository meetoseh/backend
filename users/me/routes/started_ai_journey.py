from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Optional
from error_middleware import handle_contextless_error
from models import STANDARD_ERRORS_BY_CODE
from auth import auth_any
from journeys.auth import auth_any as auth_journey_any
from itgs import Itgs
from emotions.lib.emotion_users import on_started_emotion_user_journey
from journeys.lib.notifs import on_entering_lobby

router = APIRouter()


class StartedAIJourneyRequest(BaseModel):
    journey_jwt: str = Field(
        description="The JWT for the journey, which shows that the user is authorized to start it"
    )


@router.post(
    "/started_ai_journey",
    status_code=204,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def started_ai_journey(
    args: StartedAIJourneyRequest,
    authorization: Optional[str] = Header(None),
):
    """Tracks that the user has decided to actually start the given ai journey.
    This ensures that the users history is accurate, and they won't be
    personalized towards content they haven't actually seen.

    Requires standard authorization.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        journey_auth_result = await auth_journey_any(itgs, f"bearer {args.journey_jwt}")
        if not journey_auth_result.success:
            return journey_auth_result.error_response

        await on_entering_lobby(
            itgs,
            user_sub=auth_result.result.sub,
            journey_uid=journey_auth_result.result.journey_uid,
            action=f"entering an ai journey lobby",
        )

        return Response(status_code=204)
