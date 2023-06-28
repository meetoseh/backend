import random
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Optional
from journeys.models.external_journey import ExternalJourney
from journeys.lib.read_one_external import read_one_external
from models import STANDARD_ERRORS_BY_CODE
from auth import auth_any
import journeys.auth
from users.lib.entitlements import get_entitlement
from itgs import Itgs
import time


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
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        # If they are already entitled to the pack, then don't show the offer
        entitlement = await get_entitlement(
            itgs,
            user_sub=auth_result.result.sub,
            identifier="extended-classes-pack-06272023",
        )
        if entitlement is not None and entitlement.is_active:
            return Response(status_code=204)

        # If they haven't taken a class since before at least 12 hours ago, don't show the offer
        conn = await itgs.conn()
        cursor = conn.cursor("none")
        response = await cursor.execute(
            """
            SELECT 1 FROM user_journeys, users
            WHERE
                users.sub = ?
                AND user_journeys.user_id = users.id
                AND user_journeys.created_at < ?
            LIMIT 1
            """,
            (auth_result.result.sub, time.time() - 60 * 60 * 12),
        )
        if not response.results:
            return Response(status_code=204)

        # Find available journeys
        response = await cursor.execute(
            """
            SELECT journeys.uid FROM courses, course_journeys, journeys, emotions, journey_emotions
            WHERE
                courses.slug = ?
                AND course_journeys.course_id = courses.id
                AND course_journeys.journey_id = journeys.id
                AND journey_emotions.journey_id = journeys.id
                AND emotions.word = ?
                AND journeys.deleted_at IS NULL
                AND NOT EXISTS (
                    SELECT 1 FROM user_journeys, users
                    WHERE
                        users.sub = ?
                        AND user_journeys.user_id = users.id
                        AND (
                            user_journeys.journey_id = journeys.id
                            OR user_journeys.journey_id = journeys.variation_of_journey_id
                        )
                )
            """,
            ("extended-classes-pack-06272023", args.emotion, auth_result.result.sub),
        )
        if not response.results:
            return Response(status_code=204)

        choice_journey_uids = [row[0] for row in response.results]
        journey_uid = random.choice(choice_journey_uids)
        journey_jwt = await journeys.auth.create_jwt(itgs, journey_uid=journey_uid)

        response = await read_one_external(
            itgs, journey_uid=journey_uid, jwt=journey_jwt
        )
        if response is None:
            return Response(status_code=204)

        return response
