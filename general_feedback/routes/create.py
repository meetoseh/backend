import secrets
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, StringConstraints
from typing import Annotated, Optional, Literal
from error_middleware import handle_warning
from lib.shared.describe_user import enqueue_send_described_user_slack_message
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from itgs import Itgs
from auth import auth_any
import os


class GeneralFeedbackRequest(BaseModel):
    anonymous: bool = Field(
        description="True if, after abuse protection, we should anonymize the feedback. False if we associate it with the user",
    )
    feedback: str = Field(
        description="The feedback the user is submitting",
        max_length=24000,
    )
    slug: Annotated[
        str,
        StringConstraints(min_length=1, max_length=32, pattern=r"^[a-z0-9_\\-]+$"),
    ] = Field(description="A slug which loosely identifies why we asked for feedback")


router = APIRouter()

ERROR_429_TYPES = Literal["ratelimited"]
ERROR_RATELIMITED_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_429_TYPES](
        type="ratelimited",
        message="You have exceeded the rate limit for this endpoint",
    ).model_dump_json(),
    status_code=429,
    headers={
        "Retry-After": "60",
    },
)


@router.post(
    "/",
    status_code=202,
    responses={
        **STANDARD_ERRORS_BY_CODE,
        "429": {
            "description": "The user has exceeded the rate limit for this endpoint",
        },
    },
)
async def create_general_feedback(
    args: GeneralFeedbackRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Stores general free-form feedback from the user. This request must always be
    authenticated, but the user can request that the result be anonymized after abuse
    protection mechanisms

    Requires standard authorization
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization=authorization)
        if auth_result.result is None:
            return auth_result.error_response

        ratelimit_key = (
            f"general_feedback:ratelimits:user:{auth_result.result.sub}".encode("utf-8")
        )
        redis = await itgs.redis()
        async with redis.pipeline() as pipe:
            pipe.multi()
            await pipe.incr(ratelimit_key)
            await pipe.expire(ratelimit_key, 60)
            result = await pipe.execute()

        num_requests = result[0]
        if not isinstance(num_requests, int) or num_requests >= 10:
            await handle_warning(
                f"{__name__}:ratelimited",
                f"Limiting excessive feedback from `{auth_result.result.sub=}`: `{num_requests=}`",
                is_urgent=os.environ["ENVIRONMENT"] != "dev",
            )
            return ERROR_RATELIMITED_RESPONSE

        conn = await itgs.conn()
        cursor = conn.cursor()

        feedback_uid = f"oseh_gf_{secrets.token_urlsafe(16)}"
        feedback_at = time.time()
        response = await cursor.execute(
            """
WITH batch(id) AS (VALUES (1))
INSERT INTO general_feedback (
    uid,
    user_id,
    slug,
    feedback,
    anonymous,
    created_at
)
SELECT
    ?, users.id, ?, ?, users.id IS NULL, ?
FROM batch
LEFT OUTER JOIN users ON (? = 0 AND users.sub = ?)
            """,
            (
                feedback_uid,
                args.slug,
                args.feedback,
                feedback_at,
                int(args.anonymous),
                auth_result.result.sub,
            ),
        )

        assert (
            response.rows_affected is not None and response.rows_affected > 0
        ), response
        if response.rows_affected != 1:
            await handle_warning(
                f"{__name__}:wrong_rows_affected",
                f"{response.rows_affected=}, expected 1",
            )

        if not args.anonymous:
            await enqueue_send_described_user_slack_message(
                itgs,
                message=f"{{name}} is giving feedback `{args.slug=}`\n\n{args.feedback}",
                channel="oseh_bot",
                sub=auth_result.result.sub,
            )

        # if the feedback is anonymous we can't send it instantly to slack since
        # the timing would make it obvious who sent it

        return Response(status_code=202)
