import secrets
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal, Optional
from auth import auth_any
from error_middleware import handle_contextless_error
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from itgs import Itgs


router = APIRouter()


class LikeJourneyRequest(BaseModel):
    journey_uid: str = Field(
        description="The unique identifier for the journey to like"
    )


class LikeJourneyResponse(BaseModel):
    liked_at: float = Field(
        description="When the user liked the journey in seconds since the unix epoch"
    )


ERROR_404_TYPES = Literal["journey_not_found"]
JOURNEY_NOT_FOUND_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="journey_not_found",
        message="There is no journey with that uid, or its been deleted, or the user hasn't taken it before",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=404,
)


ERROR_503_TYPES = Literal["raced"]
RACED_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_503_TYPES](
        type="raced",
        message=(
            "Either the journey does not exist or you have already liked it. "
            "Retry in a bit for a better error message"
        ),
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8", "Retry-After": "5"},
    status_code=503,
)


@router.post(
    "/journeys/likes",
    response_model=LikeJourneyResponse,
    responses={
        "404": {
            "description": "There is no journey with that uid, or its been deleted, or the user hasn't taken it before",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def like_journey(
    args: LikeJourneyRequest, authorization: Optional[str] = Header(None)
):
    """Stores that the given user likes the given journey, adding it to their
    favorite list. Unlike storing journey feedback this is a functional endpoint
    whose primary purpose is to provide an easy way to indicate journeys that
    they want to go back to later, whereas feedback is for providing information
    about the journey to the system.

    If the journey was already liked, returns success with the old liked at time.

    Requires standard authorization for a user whose taken the journey before.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor("strong")

        user_journey_uid = f"oseh_uj_{secrets.token_urlsafe(16)}"
        request_at = time.time()
        response = await cursor.executeunified3(
            (
                (
                    """
INSERT INTO user_likes (
    uid, user_id, journey_id, created_at
)
SELECT
    ?, users.id, journeys.id, ?
FROM users, journeys
WHERE
    users.sub = ?
    AND journeys.uid = ?
    AND EXISTS (
        SELECT 1 FROM user_journeys
        WHERE 
            user_journeys.user_id = users.id
            AND user_journeys.journey_id = journeys.id
    )
    AND NOT EXISTS (
        SELECT 1 FROM user_likes AS ul2
        WHERE
            ul2.user_id = users.id
            AND ul2.journey_id = journeys.id
    )
    AND journeys.deleted_at IS NULL
                    """,
                    (
                        user_journey_uid,
                        request_at,
                        auth_result.result.sub,
                        args.journey_uid,
                    ),
                ),
                (
                    """
SELECT
    user_likes.created_at
FROM user_likes, journeys, users
WHERE
    users.sub = ?
    AND journeys.uid = ?
    AND user_likes.user_id = users.id
    AND user_likes.journey_id = journeys.id
                    """,
                    (auth_result.result.sub, args.journey_uid),
                ),
                (
                    """
SELECT
    1 
FROM user_journeys, users, journeys
WHERE
    user_journeys.user_id = users.id
    AND user_journeys.journey_id = journeys.id
    AND users.sub = ?
    AND journeys.uid = ?
    AND journeys.deleted_at IS NULL
                    """,
                    (auth_result.result.sub, args.journey_uid),
                ),
            )
        )

        if response[0].rows_affected == 1:
            jobs = await itgs.jobs()
            await jobs.enqueue(
                "runners.notify_user_changed_likes",
                liked=True,
                user_sub=auth_result.result.sub,
                journey_uid=args.journey_uid,
            )
            return Response(
                content=LikeJourneyResponse(liked_at=request_at).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        if response[1].results:
            liked_at = response[1].results[0][0]
            return Response(
                content=LikeJourneyResponse(liked_at=liked_at).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        if not response[2].results:
            return JOURNEY_NOT_FOUND_RESPONSE

        await handle_contextless_error(
            extra_info=f"bad SQL for liking {args.journey_uid} by {auth_result.result.sub}:\n\n```\n{response}\n```\n"
        )
        return RACED_RESPONSE
