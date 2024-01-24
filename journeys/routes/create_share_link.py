import os
import secrets
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, StringConstraints
from typing import Annotated, Literal, Optional, cast
from error_middleware import handle_warning
from journeys.lib.link_stats import (
    incr_journey_share_link_created,
    incr_journey_share_link_reused,
)
from lib.redis_stats_preparer import redis_stats
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from itgs import Itgs
from auth import auth_any

router = APIRouter()


class CreateShareLinkRequest(BaseModel):
    uid: Annotated[str, StringConstraints(min_length=2, max_length=255)] = Field(
        description="The UID of the journey to share"
    )


class CreateShareLinkResponse(BaseModel):
    url: str = Field(description="The URL which can be shared to see that journey")


ERROR_404_TYPES = Literal["not_found"]
ERROR_NOT_FOUND_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_404_TYPES].__pydantic_serializer__.to_json(
        StandardErrorResponse[ERROR_404_TYPES](
            type="not_found",
            message="There is no journey with that uid",
        )
    ),
    status_code=404,
    headers={"Content-Type": "application/json; charset=utf-8"},
)

ERROR_409_TYPES = Literal["not_shareable"]
ERROR_NOT_SHAREABLE_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_409_TYPES].__pydantic_serializer__.to_json(
        StandardErrorResponse[ERROR_409_TYPES](
            type="not_shareable",
            message="The journey is not shareable",
        )
    ),
    status_code=409,
    headers={"Content-Type": "application/json; charset=utf-8"},
)


LINK_REUSE_TIME_SECONDS = 60 * 15


@router.post(
    "/create_share_link",
    response_model=CreateShareLinkResponse,
    responses={
        **STANDARD_ERRORS_BY_CODE,
        "404": {
            "description": "The journey with the given uid does not exist",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        "409": {
            "description": "The journey with the given uid is not shareable",
            "model": StandardErrorResponse[ERROR_409_TYPES],
        },
    },
)
async def create_share_link(
    args: CreateShareLinkRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Creates a link which can be used to share the given journey with
    other people without requiring an account. Not all journeys are shareable.

    Requires standard authorization.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor("weak")

        share_link_uid = f"oseh_jsl_{secrets.token_urlsafe(16)}"
        for i in range(5):
            generated_code = secrets.token_urlsafe(3 + i)
            now = time.time()
            response = await cursor.execute(
                """
                INSERT INTO journey_share_links (
                    uid, code, user_id, journey_id, created_at
                )
                SELECT
                    ?, ?, users.id, journeys.id, ?
                FROM users, journeys
                WHERE
                    users.sub = ?
                    AND journeys.uid = ?
                    AND journeys.deleted_at IS NULL
                    AND journeys.special_category IS NULL
                    AND NOT EXISTS (
                        SELECT 1 FROM course_journeys
                        WHERE course_journeys.journey_id = journeys.id
                    )
                    AND NOT EXISTS (
                        SELECT 1 FROM journey_share_links AS jsl
                        WHERE jsl.code = ?
                    )
                    AND NOT EXISTS (
                        SELECT 1 FROM journey_share_links AS jsl
                        WHERE
                            jsl.journey_id = journeys.id
                            AND jsl.user_id = users.id
                            AND jsl.created_at > ?
                    )
                """,
                (
                    share_link_uid,
                    generated_code,
                    now,
                    auth_result.result.sub,
                    args.uid,
                    generated_code,
                    now - LINK_REUSE_TIME_SECONDS,
                ),
            )
            if response.rows_affected is not None and response.rows_affected > 0:
                try:
                    async with redis_stats(itgs) as stats:
                        await incr_journey_share_link_created(
                            itgs, stats=stats, journey_uid=args.uid, now=now
                        )
                except Exception as e:
                    await handle_warning(
                        f"{__name__}:stats",
                        "failed to increment journey share link create stats",
                        exc=e,
                    )

                return Response(
                    content=CreateShareLinkResponse.__pydantic_serializer__.to_json(
                        CreateShareLinkResponse(
                            url=f"{os.environ['ROOT_FRONTEND_URL']}/s/{generated_code}"
                        )
                    ),
                    headers={
                        "Content-Type": "application/json; charset=utf-8",
                        "Cache-Control": f"private, max-age={LINK_REUSE_TIME_SECONDS}",
                    },
                )

            response = await cursor.execute(
                """
                SELECT
                    EXISTS (
                        SELECT 1 FROM journeys
                        WHERE
                            uid = ?
                            AND deleted_at IS NULL
                            AND special_category IS NULL
                    ) AS b1,
                    EXISTS (
                        SELECT 1 FROM journeys, course_journeys
                        WHERE
                            journeys.uid = ?
                            AND journeys.id = course_journeys.journey_id
                    ) AS b2,
                    (
                        SELECT code FROM journeys, journey_share_links, users
                        WHERE
                            journeys.uid = ?
                            AND journeys.id = journey_share_links.journey_id
                            AND users.sub = ?
                            AND users.id = journey_share_links.user_id
                            AND journey_share_links.created_at > ?
                        ORDER BY journey_share_links.created_at DESC, journey_share_links.uid DESC
                    ) AS code
                """,
                (
                    args.uid,
                    args.uid,
                    args.uid,
                    auth_result.result.sub,
                    now - LINK_REUSE_TIME_SECONDS,
                ),
            )

            assert response.results, response
            journey_exists = bool(response.results[0][0])
            journey_in_course = bool(response.results[0][1])
            code = cast(Optional[str], response.results[0][2])

            if not journey_exists:
                return ERROR_NOT_FOUND_RESPONSE
            if journey_in_course:
                return ERROR_NOT_SHAREABLE_RESPONSE
            if code is not None:
                try:
                    async with redis_stats(itgs) as stats:
                        await incr_journey_share_link_reused(
                            itgs, stats=stats, journey_uid=args.uid, now=now
                        )
                except Exception as e:
                    await handle_warning(
                        f"{__name__}:stats",
                        "failed to increment journey share link reused stats",
                        exc=e,
                    )

                return Response(
                    content=CreateShareLinkResponse.__pydantic_serializer__.to_json(
                        CreateShareLinkResponse(
                            url=f"{os.environ['ROOT_FRONTEND_URL']}/s/{code}"
                        )
                    ),
                    headers={
                        "Content-Type": "application/json; charset=utf-8",
                        "Cache-Control": f"private, max-age={LINK_REUSE_TIME_SECONDS}",
                    },
                )

        await handle_warning(
            f"{__name__}:maximum_attempts",
            f"Maximum attempts reached while trying to generate a share link for `{args.uid}` on behalf of `{auth_result.result.sub}`",
        )
        return Response(status_code=503, headers={"Retry-After": "60"})
