import socket
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import FrozenSet, Literal, Optional
from courses.lib.get_external_course_from_row import get_external_course_from_row
from error_middleware import handle_contextless_error, handle_error
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from courses.models.external_course import ExternalCourse
from auth import auth_any
from itgs import Itgs
import time
import secrets
import users.lib.entitlements as entitlements
from visitors.lib.get_or_create_visitor import (
    VisitorSource,
    get_or_create_unsanitized_visitor,
)


FREE_COURSE_SLUGS: FrozenSet[str] = frozenset(("resilient-spirit-07202023",))
"""The course slugs which, if a user requests, we will grant them the
entitlement for and then attach the course. We should probably move this
to the database once we have an admin section for courses, with a timerange
for when the course is free.
"""


class AttachFreeCourseRequest(BaseModel):
    course_slug: str = Field(
        description="The slug of the course to attach. This must be one of the free courses.",
        max_length=255,
    )
    source: VisitorSource = Field(description="The client making the request")


class AttachFreeCourseResponse(BaseModel):
    course: ExternalCourse = Field(description=("The course that was just attached"))
    visitor_uid: str = Field(
        description="The visitor uid that the client should use moving forward"
    )


router = APIRouter()
ERROR_404_TYPES = Literal["course_not_found"]
ERROR_409_TYPES = Literal["already_attached"]
ERROR_503_TYPES = Literal[
    "user_not_found",
    "failed_to_fetch_entitlement",
    "failed_to_create_entitlement",
    "failed_to_attach_course",
    "failed_to_create_response",
]


@router.post(
    "/attach_free",
    status_code=200,
    response_model=AttachFreeCourseResponse,
    responses={
        "404": {
            "description": "Course not found or is not free",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        "409": {
            "description": "Course already attached",
            "model": StandardErrorResponse[ERROR_409_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def attach_free(
    args: AttachFreeCourseRequest,
    authorization: Optional[str] = Header(None),
    visitor: Optional[str] = Header(None),
):
    """Attaches a course which is currently available for free to the authorized
    users account, granting them the appropriate entitlement to access the course.

    Requires standard authorization
    """
    request_at = time.time()
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        sanitized_visitor = await get_or_create_unsanitized_visitor(
            itgs, visitor=visitor, source=args.source, seen_at=request_at
        )

        conn = await itgs.conn()
        cursor = conn.cursor("weak")
        response = await cursor.execute(
            "SELECT revenue_cat_id, email, given_name, family_name FROM users WHERE sub=?",
            (auth_result.result.sub,),
        )
        if not response.results:
            return Response(
                content=StandardErrorResponse[ERROR_503_TYPES](
                    type="user_not_found",
                    message=(
                        "Despite valid authorization, the user you are authorizing as "
                        "does not appear to exist. If you believe this is an error, "
                        "try again in a few seconds then contact support."
                    ),
                ).json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=503,
            )

        revenue_cat_id: str = response.results[0][0]
        user_email = response.results[0][1]
        user_given_name = response.results[0][2]
        user_family_name = response.results[0][3]

        if args.course_slug not in FREE_COURSE_SLUGS:
            return Response(
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="course_not_found",
                    message=(
                        "The course you are attempting to attach does not appear to be "
                        "available for free at this time."
                    ),
                ).json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=404,
            )

        response = await cursor.execute(
            "SELECT revenue_cat_entitlement FROM courses WHERE slug=?",
            (args.course_slug,),
        )
        if not response.results:
            return Response(
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="course_not_found",
                    message=(
                        "The course you are attempting to attach does not appear to exist."
                    ),
                ).json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=404,
            )

        course_entitlement: str = response.results[0][0]

        response = await cursor.execute(
            """
            SELECT 1 FROM course_users, courses, users
            WHERE
                course_users.course_id = courses.id
                AND course_users.user_id = users.id
                AND courses.slug = ?
                AND users.sub = ?
            """,
            (args.course_slug, auth_result.result.sub),
        )

        course_is_attached = not not response.results

        try:
            existing_entitlement = await entitlements.get_entitlement(
                itgs,
                user_sub=auth_result.result.sub,
                identifier=course_entitlement,
                force=True,
            )
        except Exception as exc:
            await handle_error(
                exc,
                extra_info=(
                    f"failed to fetch entitlement {course_entitlement} (for course {args.course_slug}) "
                    f"for user {auth_result.result.sub}",
                ),
            )
            return Response(
                content=StandardErrorResponse[ERROR_503_TYPES](
                    type="failed_to_fetch_entitlement",
                    message=(
                        "An error occurred while connecting to one of our services. "
                        "Try again in a few seconds."
                    ),
                ).json(),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Retry-After": "60",
                },
                status_code=503,
            )

        if existing_entitlement.is_active and course_is_attached:
            return Response(
                content=StandardErrorResponse[ERROR_409_TYPES](
                    type="already_attached",
                    message=(
                        "You already have that course attached and available for viewing."
                    ),
                ).json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=409,
            )

        if not existing_entitlement.is_active:
            revenue_cat = await itgs.revenue_cat()
            try:
                await revenue_cat.grant_promotional_entitlement(
                    revenue_cat_id=revenue_cat_id,
                    entitlement_identifier=course_entitlement,
                    duration="lifetime",
                )
            except Exception as exc:
                await handle_error(
                    exc,
                    extra_info=(
                        f"failed to create entitlement {course_entitlement} (for course {args.course_slug}) "
                        f"for user {auth_result.result.sub} (lifetime promotional)",
                    ),
                )
                return Response(
                    content=StandardErrorResponse[ERROR_503_TYPES](
                        type="failed_to_create_entitlement",
                        message=(
                            "An error occurred while connecting to one of our services. "
                            "Try again in a few seconds."
                        ),
                    ).json(),
                    headers={
                        "Content-Type": "application/json; charset=utf-8",
                        "Retry-After": "60",
                    },
                    status_code=503,
                )

            await entitlements.purge_entitlements_from_redis(
                itgs, user_sub=auth_result.result.sub
            )
            await entitlements.publish_purge_message(
                itgs, user_sub=auth_result.result.sub, min_checked_at=time.time()
            )

        if not course_is_attached:
            course_user_uid = f"oseh_cu_{secrets.token_urlsafe(16)}"
            link_uid = f"oseh_cdl_{secrets.token_urlsafe(16)}"
            link_code = secrets.token_urlsafe(64)

            response = await cursor.executemany3(
                (
                    (
                        """
                        INSERT INTO course_users (
                            uid, course_id, user_id, last_priority, last_journey_at, created_at, updated_at
                        )
                        SELECT
                            ?, courses.id, users.id, NULL, NULL, ?, ?
                        FROM courses, users
                        WHERE
                            courses.slug = ?
                            AND users.sub = ?
                        """,
                        (
                            course_user_uid,
                            request_at,
                            request_at,
                            args.course_slug,
                            auth_result.result.sub,
                        ),
                    ),
                    (
                        """
                        INSERT INTO course_download_links (
                            uid, course_id, code, stripe_checkout_session_id, payment_email, user_id, visitor_id, created_at
                        )
                        SELECT
                            ?, courses.id, ?, NULL, users.email, users.id, visitors.id, ?
                        FROM courses, users
                        LEFT OUTER JOIN visitors ON visitors.uid = ?
                        WHERE
                            courses.slug = ?
                            AND users.sub = ?
                            AND EXISTS (SELECT 1 FROM course_users WHERE course_users.uid=?)
                        """,
                        (
                            link_uid,
                            link_code,
                            request_at,
                            sanitized_visitor,
                            args.course_slug,
                            auth_result.result.sub,
                            course_user_uid,
                        ),
                    ),
                )
            )

            if response[0].rows_affected != 1 or response[1].rows_affected != 1:
                await handle_contextless_error(
                    extra_info=(
                        f"failed to attach free course {args.course_slug} to user {auth_result.result.sub} "
                        f"despite them having the entitlement; [{response[0].rows_affected=}, {response[1].rows_affected=}]"
                    )
                )
                return Response(
                    content=StandardErrorResponse[ERROR_503_TYPES](
                        type="failed_to_attach_course",
                        message=(
                            "An error occurred while connecting to one of our services. "
                            "Try again in a few seconds."
                        ),
                    ).json(),
                    headers={
                        "Content-Type": "application/json; charset=utf-8",
                        "Retry-After": "60",
                    },
                    status_code=503,
                )

        response = await cursor.execute(
            """
            SELECT
                courses.uid,
                courses.slug,
                courses.title,
                courses.title_short,
                courses.description,
                background_image_files.uid,
                circle_image_files.uid
            FROM courses
            LEFT OUTER JOIN image_files AS background_image_files ON background_image_files.id = courses.background_image_file_id
            LEFT OUTER JOIN image_files AS circle_image_files ON circle_image_files.id = courses.circle_image_file_id
            WHERE courses.slug = ?
            """,
            (args.course_slug,),
        )
        if not response.results:
            await handle_contextless_error(
                extra_info=(
                    f"failed to fetch course {args.course_slug} for response in attach_free to user {auth_result.result.sub}"
                )
            )
            return Response(
                content=StandardErrorResponse[ERROR_503_TYPES](
                    type="failed_to_create_response",
                    message=(
                        "An error occurred while connecting to one of our services. "
                        "Try again in a few seconds."
                    ),
                ).json(),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Retry-After": "60",
                },
                status_code=503,
            )

        slack = await itgs.slack()
        await slack.send_oseh_bot_message(
            f"{socket.gethostname()} {user_given_name} {user_family_name} ({user_email} / {auth_result.result.sub}) attached free course {args.course_slug}"
        )
        return Response(
            content=AttachFreeCourseResponse(
                course=await get_external_course_from_row(
                    itgs,
                    uid=response.results[0][0],
                    slug=response.results[0][1],
                    title=response.results[0][2],
                    title_short=response.results[0][3],
                    description=response.results[0][4],
                    background_image_uid=response.results[0][5],
                    circle_image_uid=response.results[0][6],
                ),
                visitor_uid=sanitized_visitor,
            ).json(),
            headers={
                "Content-Type": "application/json; charset=utf-8",
            },
            status_code=200,
        )
