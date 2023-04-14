import json
import secrets
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, validator
from typing import Dict, Literal, Optional
from auth import auth_any
from db.utils import question_mark_list
from error_middleware import handle_contextless_error, handle_error
from models import StandardErrorResponse
from courses.models.external_course import ExternalCourse
from courses.lib.get_external_course_from_row import get_external_course_from_row
from itgs import Itgs
from visitors.lib.get_or_create_visitor import (
    VisitorSource,
    get_or_create_unsanitized_visitor,
)
import os
import stripe
import stripe.error
import pytz
from contextlib import asynccontextmanager
import socket


# idea: checkout session id exchanged for ExternalCourse
#   side effect: revenue cat user created with users information from stripe
#   side effect: revenue cat purchase created using the checkout session id
#   side effect: based on the entitlements the user now has...
#     row created in course_download_links
#     klaviyo profile create/updated to include course download link
#       this will trigger an email with the download link
#   an arbitrary course the guest account has an entitlement to is returned

# optional headers: authorization, visitor (both stored in the course download link)

# also returns their new visitor id

# idea: this is hit on the checkout landing page. the client
# also stores the checkout session id in local storage, for
# recovery.

# if the user is logged in already, they then hit the
# attach endpoint. on success, they remove it from local
# storage.

# otherwise, they see login buttons. when logging in, the
# frontend sees the checkout session id in local storage
# and hits the attach endpoint.


class ActivateCourseRequest(BaseModel):
    checkout_session_id: str = Field(description="The checkout session id to activate")
    source: VisitorSource = Field(description="The client making the request")
    timezone: str = Field(description="the new timezone")
    timezone_technique: Literal["browser"] = Field(
        description="The technique used to determine the timezone."
    )

    @validator("timezone")
    def validate_timezone(cls, v):
        if v not in pytz.all_timezones:
            raise ValueError("Must be an IANA timezone, e.g. America/New_York")
        return v


class ActivateCourseResponse(BaseModel):
    course: Optional[ExternalCourse] = Field(
        description=(
            "One of the courses that was just purchased, so it can be shown to the "
            "user to incentivize them to login for additional functionality"
        )
    )

    visitor_uid: str = Field(
        description="The visitor uid that the client should use moving forward"
    )


ERROR_404_TYPES = Literal["invalid_checkout_session"]
INVALID_CHECKOUT_SESSION_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="invalid_checkout_session",
        message=(
            "That checkout session is either already used, expired, or does not "
            "provide any course entitlements."
        ),
    ).json(),
    status_code=404,
    headers={"Content-Type": "application/json; charset=utf-8"},
)
ERROR_429_TYPES = Literal["too_many_requests"]
ERROR_503_TYPES = Literal["concurrent_request"]
CONCURRENT_REQUEST_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_503_TYPES](
        type="concurrent_request",
        message=(
            "Another request is currently processing this checkout session. "
            "Please try again in a few seconds."
        ),
    ).json(),
    status_code=503,
    headers={
        "Content-Type": "application/json; charset=utf-8",
        "Retry-After": "5",
    },
)


class LockHeldError(Exception):
    def __init__(self, checkout_session_id: str):
        super().__init__(f"Lock already held for {checkout_session_id=}")


router = APIRouter()


@router.post(
    "/activate",
    response_model=ActivateCourseResponse,
    responses={
        "404": {
            "description": "That checkout session doesn't grant course entitlements",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        "429": {
            "description": "Too many requests",
            "model": StandardErrorResponse[ERROR_429_TYPES],
        },
    },
)
async def activate_course(
    args: ActivateCourseRequest,
    visitor: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
):
    """Finalizes the given stripe checkout session. If it is a valid completed
    checkout session for one or more courses, the user will be emailed download
    links for the courses and one of those courses will be returned.

    This endpoint does not attach the activated course to the users account, and
    does not require that the user be logged in (the authorization header may
    be omitted or invalid without preventing the emails from being sent).

    Use the attach endpoint once the user is logged in to attach the course
    to the users account, which provides access to the additional features
    for the course - streaming, streaks, and so on.

    If the device already has a visitor id, or the user is already logged in,
    the corresponding headers should be sent.
    """
    request_at = time.time()

    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        sanitized_visitor = await get_or_create_unsanitized_visitor(
            itgs, visitor=visitor, source=args.source, seen_at=request_at
        )

        stripe_sk = os.environ["OSEH_STRIPE_SECRET_KEY"]
        try:
            checkout_session = stripe.checkout.Session.retrieve(
                args.checkout_session_id, api_key=stripe_sk
            )
        except stripe.error.InvalidRequestError as e:
            await handle_error(
                exc=e,
                extra_info=f"while activating {args.checkout_session_id=} for {sanitized_visitor=}, {auth_result.result=}",
            )
            return INVALID_CHECKOUT_SESSION_RESPONSE

        if checkout_session.status != "complete":
            await handle_contextless_error(
                extra_info=f"while activating {args.checkout_session_id=}, got incomplete checkout session ({checkout_session.status=}) for {sanitized_visitor=}, {auth_result.result=}"
            )
            return INVALID_CHECKOUT_SESSION_RESPONSE

        if checkout_session.payment_status not in ("paid", "no_payment_required"):
            await handle_contextless_error(
                extra_info=f"while activating {args.checkout_session_id=}, got incomplete checkout session ({checkout_session.payment_status=}) for {sanitized_visitor=}, {auth_result.result=}"
            )
            return INVALID_CHECKOUT_SESSION_RESPONSE

        try:
            async with course_activation_lock(itgs, args.checkout_session_id):
                conn = await itgs.conn()
                cursor = conn.cursor("weak")

                # check if we've already activated this checkout session
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
                    WHERE
                        EXISTS (
                            SELECT 1 FROM course_download_links
                            WHERE
                                course_download_links.course_id = courses.id
                                AND course_download_links.stripe_checkout_session_id = ?
                        )
                    ORDER BY courses.revenue_cat_entitlement ASC
                    LIMIT 1
                    """,
                    (args.checkout_session_id,),
                )

                if response.results:
                    row = response.results[0]
                    course = await get_external_course_from_row(
                        itgs,
                        uid=row[0],
                        slug=row[1],
                        title=row[2],
                        title_short=row[3],
                        description=row[4],
                        background_image_file_uid=row[5],
                        circle_image_file_uid=row[6],
                    )
                    return Response(
                        content=ActivateCourseResponse(
                            course=course,
                            visitor_uid=sanitized_visitor,
                        ).json(),
                        headers={"Content-Type": "application/json; charset=utf-8"},
                        status_code=200,
                    )

                revenue_cat = await itgs.revenue_cat()
                new_rc_id = f"oseh_g_rc_{secrets.token_urlsafe(16)}"
                # order is important; create_stripe purchase creates an account
                # if it doesn't exist, set_customer_attributes does not
                customer = await revenue_cat.create_stripe_purchase(
                    revenue_cat_id=new_rc_id,
                    stripe_checkout_session_id=args.checkout_session_id,
                )
                email: str = checkout_session.customer_details.email
                name: str = checkout_session.customer_details.name
                await revenue_cat.set_customer_attributes(
                    revenue_cat_id=new_rc_id,
                    attributes={
                        "$email": email,
                        "$displayName": name,
                        "environment": os.environ["ENVIRONMENT"],
                        "guestInfo": json.dumps(
                            {
                                "visitor": sanitized_visitor,
                                "user_sub": None
                                if auth_result.result is None
                                else auth_result.result.sub,
                            }
                        ),
                        "client": args.source,
                        "endpoint": "courses/routes/activate",
                    },
                )

                active_entitlement_idens = [
                    iden
                    for iden, entitlement in customer.subscriber.entitlements.items()
                    if entitlement.expires_date is None
                    or entitlement.expires_date.timestamp() > request_at
                ]

                if not active_entitlement_idens:
                    return Response(
                        content=ActivateCourseResponse(
                            course=None,
                            visitor_uid=sanitized_visitor,
                        ).json(),
                        headers={"Content-Type": "application/json; charset=utf-8"},
                        status_code=200,
                    )

                course_links: Dict[str, str] = dict()
                best_course: Optional[ExternalCourse] = None
                response = await cursor.execute(
                    f"""
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
                    WHERE
                        courses.revenue_cat_entitlement IN ({question_mark_list(len(active_entitlement_idens))})
                    ORDER BY courses.revenue_cat_entitlement ASC
                    """,
                    (args.checkout_session_id, *active_entitlement_idens),
                )

                for row in response.results or []:
                    if best_course is None:
                        best_course = await get_external_course_from_row(
                            itgs,
                            uid=row[0],
                            slug=row[1],
                            title=row[2],
                            title_short=row[3],
                            description=row[4],
                            background_image_file_uid=row[5],
                            circle_image_file_uid=row[6],
                        )

                    link_uid = f"oseh_cdl_{secrets.token_urlsafe(16)}"
                    code = secrets.token_urlsafe(64)
                    course_links[row[1]] = (
                        os.environ["ROOT_FRONTEND_URL"]
                        + "/courses/download?code="
                        + code
                    )

                    await cursor.execute(
                        """
                        INSERT INTO course_download_links (
                            uid,
                            course_id,
                            code,
                            stripe_checkout_session_id,
                            user_id,
                            visitor_id,
                            created_at
                        )
                        SELECT
                            ?, courses.id, ?, ?, users.id, visitors.id, ?
                        FROM courses
                        LEFT OUTER JOIN users ON (? IS NOT NULL AND users.sub = ?)
                        LEFT OUTER JOIN visitors ON visitors.uid = ?
                        WHERE
                            courses.uid = ?
                        """,
                        (
                            link_uid,
                            code,
                            args.checkout_session_id,
                            request_at,
                            auth_result.result.sub if auth_result.success else None,
                            auth_result.result.sub if auth_result.success else None,
                            sanitized_visitor,
                            row[0],
                        ),
                    )

                klaviyo = await itgs.klaviyo()
                new_profile_id = await klaviyo.get_profile_id(email=email)
                if new_profile_id is None:
                    split_name = name.rsplit(" ", 1)
                    given_name = split_name[0]
                    family_name = split_name[1] if len(split_name) > 1 else ""
                    new_profile_id = await klaviyo.create_profile(
                        email=email,
                        phone_number=None,
                        external_id=new_rc_id,
                        first_name=given_name,
                        last_name=family_name,
                        timezone=args.timezone,
                        environment=os.environ["ENVIRONMENT"],
                        course_links_by_slug=course_links,
                    )
                else:
                    await klaviyo.update_profile(
                        profile_id=new_profile_id,
                        course_links_by_slug=course_links,
                        preserve_phone=True,
                    )

                slack = await itgs.slack()
                await slack.send_oseh_bot_message(
                    f"{socket.gethostname()} - {name} ({email}) just purchased the following courses: {', '.join(course_links.keys())}"
                )
                return Response(
                    content=ActivateCourseResponse(
                        course=best_course,
                        visitor_uid=sanitized_visitor,
                    ).json(),
                    headers={"Content-Type": "application/json; charset=utf-8"},
                    status_code=200,
                )
        except LockHeldError as e:
            await handle_error(
                e, extra_info=f"while activating {args.checkout_session_id=}"
            )
            return CONCURRENT_REQUEST_RESPONSE


@asynccontextmanager
async def course_activation_lock(itgs: Itgs, stripe_checkout_session_id: str):
    """An asynchronous context manager which uses redis to act as a distributed
    lock on the checkout session with the given id. This isn't a perfect lock,
    so this should primarily be used to make debugging easier rather than as
    a necessary part of the system.
    """
    key = f"course_activations:{stripe_checkout_session_id}:lock".encode("utf-8")

    redis = await itgs.redis()
    success = await redis.set(key, b"1", ex=120, nx=True)
    if not success:
        raise LockHeldError(stripe_checkout_session_id)

    try:
        yield
    finally:
        await redis.delete(key)
