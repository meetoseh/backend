from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Optional, Literal
from journeys.routes.read import Journey
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from auth import auth_admin
from itgs import Itgs
from journeys.routes.read import raw_read_journeys
import secrets
import time

from resources.filter_text_item import FilterTextItem
from resources.standard_text_operator import StandardTextOperator


class CreateIntroductoryJourneyRequest(BaseModel):
    journey_uid: str = Field(
        description="The uid of the journey to mark as introductory"
    )


class CreateIntroductoryJourneyResponse(BaseModel):
    uid: str = Field(
        description="The uid of the newly created introductory journey row"
    )
    journey: Journey = Field(description="The journey that was marked as introductory")
    user_sub: str = Field(
        description="The sub of the user who marked the journey as introductory"
    )
    created_at: float = Field(
        description="The time at which the row was created, in seconds since the epoch"
    )


ERROR_404_TYPES = Literal["journey_not_found"]
ERROR_409_TYPES = Literal["journey_already_introductory", "journey_deleted"]


router = APIRouter()


@router.post(
    "/",
    status_code=201,
    response_model=CreateIntroductoryJourneyResponse,
    responses={
        "404": {
            "model": StandardErrorResponse[ERROR_404_TYPES],
            "description": "There is no journey with that uid",
        },
        "409": {
            "model": StandardErrorResponse[ERROR_409_TYPES],
            "description": "The journey is already introductory, or has been deleted",
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def create_introductory_journey(
    args: CreateIntroductoryJourneyRequest, authorization: Optional[str] = Header(None)
):
    """Marks a journey as introductory. A journey which is marked introductory can
    be selected from when a user joins for the first time as the class that the user
    is pushed into.

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor("weak")

        # since we need the journey for the response anyway, we'd rather
        # grab it before the create so we don't have to fail the create
        # if the create succeeded but the journey was deleted afterward
        matching_journeys = await raw_read_journeys(
            itgs,
            [
                (
                    "uid",
                    FilterTextItem(
                        operator=StandardTextOperator.EQUAL_CASE_SENSITIVE,
                        value=args.journey_uid,
                    ),
                ),
            ],
            [],
            limit=1,
        )
        if len(matching_journeys) != 1:
            return Response(
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="journey_not_found",
                    message="There is no journey with that uid",
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        journey = matching_journeys[0]
        if journey.deleted_at is not None:
            return Response(
                content=StandardErrorResponse[ERROR_409_TYPES](
                    type="journey_deleted",
                    message="The journey has been deleted",
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        uid = f"oseh_ij_{secrets.token_urlsafe(16)}"
        now = time.time()
        response = await cursor.execute(
            """
            INSERT INTO introductory_journeys (
                uid, journey_id, user_id, created_at
            )
            SELECT
                ?, journeys.id, users.id, ?
            FROM journeys, users
            WHERE
                journeys.uid = ?
                AND users.sub = ?
                AND journeys.deleted_at IS NULL
                AND NOT EXISTS (
                    SELECT 1 FROM introductory_journeys
                    WHERE introductory_journeys.journey_id = journeys.id
                )
            """,
            (uid, now, args.journey_uid, auth_result.result.sub),
        )

        if response.rows_affected is not None and response.rows_affected > 0:
            return Response(
                content=CreateIntroductoryJourneyResponse(
                    uid=uid,
                    journey=journey,
                    user_sub=auth_result.result.sub,
                    created_at=now,
                ).model_dump_json(),
                status_code=201,
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        return Response(
            content=StandardErrorResponse[ERROR_409_TYPES](
                type="journey_already_introductory",
                message="The journey is already introductory",
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
