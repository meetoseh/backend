# restores all the purchases made in the given checkout session id to
# the users account and returns 202 accepted. the frontend should then
# go through the normal method of handling courses (/api/1/courses/mine)

# this also starts all courses that the user has an entitlement to & hasn't
# started, since for now there's no other method to start courses. if a ui is
# created where the user can browse their courses and start them, this part
# would be removed.
import secrets
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal, Optional
from db.utils import question_mark_list
from itgs import Itgs
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from auth import auth_any
import users.lib.entitlements
import time
import socket


class AttachCourseRequest(BaseModel):
    checkout_session_id: str = Field(
        description="The checkout session id to restore purchases from"
    )


router = APIRouter()
ERROR_429_TYPES = Literal["too_many_requests"]
ERROR_503_TYPES = Literal["user_not_found"]


@router.post(
    "/attach",
    status_code=202,
    responses={
        "429": {
            "description": "Too many requests",
            "model": StandardErrorResponse[ERROR_429_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def attach_course(
    args: AttachCourseRequest, authorization: Optional[str] = Header(None)
):
    """Attaches any courses granted from the given checkout session to the
    authorized users account. This should always be used after activating
    the checkout session, even if the user is already logged in when
    landing on the checkout page.

    This also starts any courses the user has access to but hasn't started as
    there's no other way to do so currently. Once another way of starting
    courses is added, this behavior will be removed.

    Requires standard authorization.
    """
    request_at = time.time()
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor("weak")
        response = await cursor.execute(
            "SELECT revenue_cat_id FROM users WHERE sub=?", (auth_result.result.sub,)
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

        revenue_cat_id = response.results[0][0]

        revenue_cat = await itgs.revenue_cat()
        customer = await revenue_cat.create_stripe_purchase(
            revenue_cat_id=revenue_cat_id,
            stripe_checkout_session_id=args.checkout_session_id,
            is_restore=True,
        )

        await users.lib.entitlements.purge_entitlements_from_redis(
            itgs, user_sub=auth_result.result.sub
        )
        await users.lib.entitlements.publish_purge_message(
            itgs, user_sub=auth_result.result.sub, min_checked_at=time.time()
        )

        active_entitlement_idens = [
            iden
            for iden, entitlement in customer.subscriber.entitlements.items()
            if entitlement.expires_date is None
            or entitlement.expires_date.timestamp() > request_at
        ]
        if not active_entitlement_idens:
            return Response(status_code=202)

        response = await cursor.execute(
            f"""
            SELECT courses.uid, courses.slug FROM courses
            WHERE
                courses.revenue_cat_entitlement IN ({question_mark_list(len(active_entitlement_idens))})
                AND NOT EXISTS (
                    SELECT 1 FROM course_users
                    WHERE
                        course_users.course_id = courses.id
                        AND EXISTS (
                            SELECT 1 FROM users
                            WHERE users.id = course_users.user_id
                              AND users.sub = ?
                        )
                )
            """,
            [
                *active_entitlement_idens,
                auth_result.result.sub,
            ],
        )
        if not response.results:
            return Response(status_code=202)

        course_uids_to_start = [row[0] for row in response.results]
        course_slugs_to_start = [row[1] for row in response.results]
        courses_to_add = [
            (course_uid, f"oseh_cu_{secrets.token_urlsafe(16)}")
            for course_uid in course_uids_to_start
        ]
        courses_to_add_qmarks = ", ".join(["(?, ?)" for _ in courses_to_add])
        await cursor.execute(
            f"""
            WITH courses_to_add(course_uid, new_course_user_uid) AS (VALUES {courses_to_add_qmarks})
            INSERT INTO course_users (
                uid, course_id, user_id, last_priority, last_journey_at, created_at, updated_at
            )
            SELECT
                courses_to_add.new_course_user_uid,
                courses.id,
                users.id,
                NULL,
                NULL,
                ?,
                ?
            FROM courses_to_add, courses, users
            WHERE
                courses.uid = courses_to_add.course_uid
                AND users.sub = ?
            """,
            (
                *[i for tup in courses_to_add for i in tup],
                request_at,
                request_at,
                auth_result.result.sub,
            ),
        )

        slack = await itgs.slack()
        identifier = (
            f"{auth_result.result.claims['name']} ({auth_result.result.claims['email']})"
            if auth_result.result.claims is not None
            and "name" in auth_result.result.claims
            and "email" in auth_result.result.claims
            else auth_result.result.sub
        )
        await slack.send_oseh_bot_message(
            f"{socket.gethostname()}: {identifier} has started the following courses: {', '.join(course_slugs_to_start)}"
        )
        return Response(status_code=202)
