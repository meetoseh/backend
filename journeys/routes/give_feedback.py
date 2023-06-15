from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, constr
from typing import List, Optional, Literal
from auth import auth_any
from journeys.auth import auth_any as auth_journey_any
from models import (
    STANDARD_ERRORS_BY_CODE,
    StandardErrorResponse,
    AUTHORIZATION_UNKNOWN_TOKEN,
)
from itgs import Itgs
from dataclasses import dataclass
import secrets
import time


@dataclass
class FeedbackVersion:
    version: str
    """
    The unique identifier for this question. More details about this question
    is in the docs under the `journey_feedback` table
    """

    version_number: int
    """The number we use to indicate this version in the database"""

    num_responses: int
    """The number of responses to the freeform question. We store the responses 1-indexed"""

    allows_freeform: bool
    """Whether or not the user is allowed to provide freeform feedback"""

    slack_messages: List[Optional[str]]
    """The slack message to post for each response, or None to not post a message for
    that response.
    """


FEEDBACKS_BY_VERSION = {
    "oseh_jf-otp_fKWQzTG-JnA": FeedbackVersion(
        version="oseh_jf-otp_fKWQzTG-JnA",
        version_number=1,
        num_responses=2,
        allows_freeform=False,
        slack_messages=["liked", "disliked"],
    ),
    "oseh_jf-otp_gwJjdMC4820": FeedbackVersion(
        version="oseh_jf-otp_gwJjdMC4820",
        version_number=2,
        num_responses=2,
        allows_freeform=False,
        slack_messages=["liked", "disliked"],
    ),
    "oseh_jf-otp_sKjKVHs8wbI": FeedbackVersion(
        version="oseh_jf-otp_sKjKVHs8wbI",
        version_number=3,
        num_responses=4,
        allows_freeform=False,
        slack_messages=["loved", "liked", "disliked", "hated"],
    ),
}

router = APIRouter()


class FeedbackRequest(BaseModel):
    journey_uid: str = Field(
        description="The uid of the journey that the feedback is for"
    )
    journey_jwt: str = Field(
        description="The JWT that shows you have access to that journey"
    )
    version: str = Field(
        description="The unique identifier which indicates which question the user was asked"
    )
    response: int = Field(
        description="The users response to the multiple choice part of the question, 1-indexed"
    )
    feedback: Optional[constr(max_length=1000, strip_whitespace=True)] = Field(
        description="If the user provided freeform feedback, that freeform feedback"
    )


ERROR_404_TYPES = Literal["version_not_found"]
ERROR_409_TYPES = Literal["invalid_response"]
ERROR_503_TYPES = Literal["integrity_error"]


@router.post(
    "/feedback",
    status_code=201,
    responses={
        "404": {
            "description": "The journey or version was not found",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        "409": {
            "description": "The indicated response is not valid for the given version",
            "model": StandardErrorResponse[ERROR_409_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def give_feedback(
    args: FeedbackRequest, authorization: Optional[str] = Header(None)
):
    """Provides feedback about the given journey. Can be called multiple times
    in case the user wants to change their feedback.

    Requires standard authorization alongside a valid JWT for the journey
    """
    async with Itgs() as itgs:
        std_auth_result = await auth_any(itgs, authorization)
        if not std_auth_result.success:
            return std_auth_result.error_response

        journey_auth_result = await auth_journey_any(itgs, f"bearer {args.journey_jwt}")
        if not journey_auth_result.success:
            return journey_auth_result.error_response
        if journey_auth_result.result.journey_uid != args.journey_uid:
            return AUTHORIZATION_UNKNOWN_TOKEN

        feedback_version = FEEDBACKS_BY_VERSION.get(args.version)
        if feedback_version is None:
            return Response(
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="version_not_found",
                    message="The indicated feedback question does not exist",
                ).json(),
                status_code=404,
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                },
            )

        if not feedback_version.allows_freeform and args.feedback is not None:
            return Response(
                content=StandardErrorResponse[ERROR_409_TYPES](
                    type="invalid_response",
                    message="The indicated feedback question does not allow freeform feedback",
                ).json(),
                status_code=409,
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                },
            )

        if args.response < 1 or args.response > feedback_version.num_responses:
            return Response(
                content=StandardErrorResponse[ERROR_409_TYPES](
                    type="invalid_response",
                    message="The indicated response is not valid for the given version",
                ).json(),
                status_code=409,
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                },
            )

        conn = await itgs.conn()
        cursor = conn.cursor("weak")

        feedback_uid = f"oseh_jf_{secrets.token_urlsafe(16)}"
        now = time.time()
        response = await cursor.execute(
            """
            INSERT INTO journey_feedback (
                uid, user_id, journey_id, version, response, freeform, created_at
            )
            SELECT
                ?, users.id, journeys.id, ?, ?, ?, ?
            FROM users, journeys
            WHERE
                users.sub = ? AND journeys.uid = ?
            """,
            (
                feedback_uid,
                feedback_version.version_number,
                args.response,
                args.feedback,
                now,
                std_auth_result.result.sub,
                journey_auth_result.result.journey_uid,
            ),
        )
        if response.rows_affected is None or response.rows_affected < 1:
            return Response(
                content=StandardErrorResponse[ERROR_503_TYPES](
                    type="integrity_error", message="The feedback could not be saved"
                ).json(),
                status_code=503,
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Retry-After": "5",
                },
            )

        if feedback_version.slack_messages[args.response - 1] is not None:
            jobs = await itgs.jobs()
            await jobs.enqueue(
                "runners.notify_on_entering_lobby",
                user_sub=std_auth_result.result.sub,
                journey_uid=journey_auth_result.result.journey_uid,
                action=f"providing feedback: {feedback_version.slack_messages[args.response - 1]}",
            )

        return Response(status_code=201)
