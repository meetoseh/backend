from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, validator
from typing import Literal, Optional
from auth import auth_admin
from itgs import Itgs
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
import time
import secrets


router = APIRouter()


# we don't want to embed any of the defaults into the frontend, and we definitely
# don't want them in the api docs, so this is a little more tedious than normal


class Phone04102023VariantInternal(BaseModel):
    """The display data for this variant, in the database"""

    phone_number: Optional[str] = Field(
        None,
        description="The phone number of the founder to text, E.164 format. None for the current default",
    )
    text_prefill: Optional[str] = Field(
        None,
        description="The text the user should have prefilled in the sms link. None for the current default",
    )
    background_image_uid: Optional[str] = Field(
        None, description="The background image to use. None for the current default"
    )
    image_uid: Optional[str] = Field(
        None,
        description="The image of the founder, or similar. None for the current default",
    )
    image_caption: Optional[str] = Field(
        None, description="The caption of the image. None for the current default"
    )
    title: Optional[str] = Field(
        None, description="The title text to display. None for the current default"
    )
    message: Optional[str] = Field(
        None, description="The message to display. None for the current default"
    )
    cta: Optional[str] = Field(
        None, description="The call-to-action text. None for the current default"
    )


class CreateVipChatRequestRequest(BaseModel):
    user_sub: Optional[str] = Field(
        description="The sub of the user who should recieve the chat request."
    )
    user_email: Optional[str] = Field(
        description=(
            "The email of the user who should recieve the chat request. "
            "Ignored if the sub is provided. Ties result in an error"
        )
    )
    variant: Literal["phone-04102023"] = Field(
        description="Which prompt to show the user"
    )
    display_data: Phone04102023VariantInternal = Field(
        description="The display data, which depends on the variant"
    )
    reason: Optional[str] = Field(
        description="Why we are sending this chat request. This is for debugging purposes only."
    )

    @validator("user_sub", "user_email")
    def user_sub_or_user_email(cls, v, values):
        if v is None and values.get("user_email") is None:
            raise ValueError("Either user_sub or user_email must be provided")
        return v


class CreateVipChatRequestResponse(BaseModel):
    uid: str = Field(description="The uid of the newly created chat request")
    user_sub: str = Field(
        description="The sub of the user who should recieve the chat request."
    )
    added_by_user_sub: str = Field(
        description="The sub of the user who created this chat request"
    )
    variant: Literal["phone-04102023"] = Field(
        description="Which prompt to show the user"
    )
    display_data: Phone04102023VariantInternal = Field(
        description="The display data, which depends on the variant"
    )
    reason: Optional[str] = Field(
        description="Why we are sending this chat request. This is for debugging purposes only."
    )


ERROR_404_TYPES = Literal[
    "user_not_found",
    "background_image_not_found",
    "image_not_found",
]
ERROR_409_TYPES = Literal[
    "user_has_pending_request",
    "multiple_users_found",
]


@router.post(
    "/",
    status_code=201,
    response_model=CreateVipChatRequestResponse,
    responses={
        "404": {
            "model": StandardErrorResponse[ERROR_404_TYPES],
            "description": "There is no user with that sub",
        },
        "409": {
            "model": StandardErrorResponse[ERROR_409_TYPES],
            "description": "The user already has a pending vip chat request, or there are multiple matching users",
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def create_vip_chat_request(
    args: CreateVipChatRequestRequest,
    authorization: Optional[str] = Header(None),
):
    """Creates a new vip chat request for the user with the given sub, which
    they will see next time they view the website or open the app.

    Requires standard authorization for an admin user.
    """
    if args.reason is not None:
        args.reason = args.reason.strip()
        if args.reason == "":
            args.reason = None

    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor()

        if args.user_sub is None:
            response = await cursor.execute(
                "SELECT sub FROM users WHERE email = ? LIMIT 2",
                (args.user_email,),
            )
            if not response.results:
                return Response(
                    status_code=404,
                    content=StandardErrorResponse[ERROR_404_TYPES](
                        type="user_not_found",
                        message="There is no user with that email",
                    ).json(),
                    headers={
                        "Content-Type": "application/json; charset=utf-8",
                    },
                )
            if len(response.results) > 1:
                return Response(
                    status_code=409,
                    content=StandardErrorResponse[ERROR_409_TYPES](
                        type="multiple_users_found",
                        message="There are multiple users with that email",
                    ).json(),
                    headers={
                        "Content-Type": "application/json; charset=utf-8",
                    },
                )
            args.user_sub = response.results[0][0]

        response = await cursor.execute(
            "SELECT given_name FROM users WHERE sub = ?",
            (args.user_sub,),
        )
        if not response.results:
            return Response(
                status_code=404,
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="user_not_found",
                    message="There is no user with that sub",
                ).json(),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                },
            )

        given_name: str = response.results[0][0]
        if given_name == "Anonymous":
            given_name = "there"

        if args.variant == "phone-04102023":
            if args.display_data.phone_number is None:
                args.display_data.phone_number = "+18184825279"
            if args.display_data.text_prefill is None:
                args.display_data.text_prefill = (
                    "Hi Ashley! I'd love to chat. What time were you thinking?"
                )
            if args.display_data.background_image_uid is None:
                # this is the oseh_ocean_bg created by the frontend-web, so it'll be in all envs
                args.display_data.background_image_uid = (
                    "oseh_if_hH68hcmVBYHanoivLMgstg"
                )
            if args.display_data.image_uid is None:
                # this has to be uploaded manually since it's private, using the job
                # runner upload_vip_chat_request_image.
                redis = await itgs.redis()
                raw_uid = await redis.get("vip_chat_request_image_uid")
                if raw_uid is None:
                    raise Exception("vip_chat_request_image_uid not found in redis")
                if not isinstance(raw_uid, bytes):
                    raise Exception("vip_chat_request_image_uid is not bytes")
                args.display_data.image_uid = raw_uid.decode("utf-8")
            if args.display_data.image_caption is None:
                args.display_data.image_caption = "Actual photo of me as a kid"
            if args.display_data.title is None:
                args.display_data.title = f"Hi {given_name}"
            if args.display_data.message is None:
                args.display_data.message = "You’re an Oseh VIP and we’d love to partner with you on how to make Oseh even better."
            if args.display_data.cta is None:
                args.display_data.cta = "Let’s Chat"

        response = await cursor.execute(
            """
            SELECT
                EXISTS (
                    SELECT 1 FROM image_files WHERE uid=?
                ) AS b1,
                EXISTS (
                    SELECT 1 FROM image_files WHERE uid=?
                ) AS b2
            """,
            (
                args.display_data.background_image_uid,
                args.display_data.image_uid,
            ),
        )
        if not response.results[0][0]:
            return Response(
                status_code=404,
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="background_image_not_found",
                    message="The background image was not found",
                ).json(),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                },
            )
        if not response.results[0][1]:
            return Response(
                status_code=404,
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="image_not_found",
                    message="The image was not found",
                ).json(),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                },
            )

        uid = f"oseh_vcr_{secrets.token_urlsafe(16)}"
        now = time.time()

        response = await cursor.execute(
            """INSERT INTO vip_chat_requests (
                uid,
                user_id,
                added_by_user_id,
                display_data,
                variant,
                reason,
                created_at,
                popup_seen_at
            )
            SELECT
                ?, users.id, added_by_users.id, ?, ?, ?, ?, NULL
            FROM users, users AS added_by_users
            WHERE
                users.sub = ?
                AND added_by_users.sub = ?
                AND NOT EXISTS (
                    SELECT 1 FROM vip_chat_requests vcr
                    WHERE vcr.user_id = users.id
                      AND vcr.popup_seen_at IS NULL
                )
            """,
            (
                uid,
                args.display_data.json(),
                args.variant,
                args.reason,
                now,
                args.user_sub,
                auth_result.result.sub,
            ),
        )

        if response.rows_affected is not None and response.rows_affected > 0:
            return Response(
                content=CreateVipChatRequestResponse(
                    uid=uid,
                    user_sub=args.user_sub,
                    added_by_user_sub=auth_result.result.sub,
                    variant=args.variant,
                    display_data=args.display_data,
                    reason=args.reason,
                ).json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=201,
            )

        response = await cursor.execute(
            "SELECT 1 FROM users WHERE sub=?", (args.user_sub,)
        )
        if not response.results:
            return Response(
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="user_not_found",
                    message="There is no user with that sub",
                ).json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=404,
            )

        return Response(
            content=StandardErrorResponse[ERROR_409_TYPES](
                type="user_has_pending_request",
                message="The user already has a pending vip chat request",
            ).json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=409,
        )
