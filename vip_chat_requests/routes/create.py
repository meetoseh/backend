from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, validator
from typing import Literal, Optional, cast
from auth import auth_admin
from image_files.models import ImageFileRef
from image_files.auth import create_jwt as create_image_file_jwt
from itgs import Itgs
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
import time
import secrets


router = APIRouter()


class User(BaseModel):
    sub: str = Field(description="The sub of the user")
    given_name: str = Field(description="The given name of the user")
    family_name: str = Field(description="The family name of the user")
    created_at: float = Field(
        description="The time the user was created in seconds since the epoch"
    )


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


class Phone04102023VariantAdmin(BaseModel):
    """The display data for this variant, in the database"""

    phone_number: str = Field(
        description="The phone number of the founder to text, E.164 format"
    )
    text_prefill: str = Field(
        description="The text the user should have prefilled in the sms link"
    )
    background_image: ImageFileRef = Field(description="The background image")
    image: ImageFileRef = Field(description="The image of the founder, or similar")
    image_caption: str = Field(description="The caption of the image")
    title: str = Field(description="The title text to display")
    message: str = Field(description="The message to display")
    cta: str = Field(description="The call-to-action text")


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
    user: User = Field(description="The user who should recieve the chat request.")
    added_by_user: User = Field(description="The user who created this chat request")
    variant: Literal["phone-04102023"] = Field(
        description="Which prompt to show the user"
    )
    display_data: Phone04102023VariantAdmin = Field(
        description="The display data, which depends on the variant"
    )
    reason: Optional[str] = Field(
        description="Why we are sending this chat request. This is for debugging purposes only."
    )
    created_at: float = Field(
        description="The time the chat request was created in seconds since the epoch"
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
        if auth_result.result is None:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor()

        if args.user_sub is None:
            response = await cursor.execute(
                """
                SELECT
                    users.sub 
                FROM users
                WHERE
                    EXISTS (
                        SELECT 1 FROM user_email_addresses 
                        WHERE 
                            user_email_addresses.user_id = users.id
                            AND user_email_addresses.email = ?
                    )
                LIMIT 2
                """,
                (args.user_email,),
            )
            if not response.results:
                return Response(
                    status_code=404,
                    content=StandardErrorResponse[ERROR_404_TYPES](
                        type="user_not_found",
                        message="There is no user with that email",
                    ).model_dump_json(),
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
                    ).model_dump_json(),
                    headers={
                        "Content-Type": "application/json; charset=utf-8",
                    },
                )
            args.user_sub = cast(str, response.results[0][0])

        response = await cursor.execute(
            "SELECT given_name, family_name, created_at FROM users WHERE sub = ?",
            (args.user_sub,),
        )
        if not response.results:
            return Response(
                status_code=404,
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="user_not_found",
                    message="There is no user with that sub",
                ).model_dump_json(),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                },
            )

        given_name: str = response.results[0][0]
        if given_name == "Anonymous":
            given_name = "there"

        (
            user_given_name,
            user_family_name,
            user_created_at,
        ) = response.results[0]

        response = await cursor.execute(
            "SELECT given_name, family_name, created_at FROM users WHERE sub = ?",
            (auth_result.result.sub,),
        )
        if not response.results:
            raise Exception("admin user deleted mid-request?")

        (
            added_by_user_given_name,
            added_by_user_family_name,
            added_by_user_created_at,
        ) = response.results[0]

        if args.variant == "phone-04102023":
            if args.display_data.phone_number is None:
                args.display_data.phone_number = "+15104999158"
            if args.display_data.text_prefill is None:
                args.display_data.text_prefill = (
                    "Hi Paul! I'd love to chat. What time were you thinking?"
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
                args.display_data.image_caption = "Hi I’m Paul, I’m a founder of Oseh"
            if args.display_data.title is None:
                args.display_data.title = "$25 to help us out"
            if args.display_data.message is None:
                args.display_data.message = "You’re an Oseh VIP and I’d love to learn how we can make Oseh even better. As a thank you for taking the time to chat, we'll gift you a $25 gift card."
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
        assert response.results
        if not response.results[0][0]:
            return Response(
                status_code=404,
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="background_image_not_found",
                    message="The background image was not found",
                ).model_dump_json(),
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
                ).model_dump_json(),
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
                args.display_data.model_dump_json(),
                args.variant,
                args.reason,
                now,
                args.user_sub,
                auth_result.result.sub,
            ),
        )

        if response.rows_affected is not None and response.rows_affected > 0:
            assert args.display_data.background_image_uid is not None
            assert args.display_data.image_uid is not None
            assert args.display_data.phone_number is not None
            assert args.display_data.text_prefill is not None
            assert args.display_data.image_caption is not None
            assert args.display_data.title is not None
            assert args.display_data.message is not None
            assert args.display_data.cta is not None
            return Response(
                content=CreateVipChatRequestResponse(
                    uid=uid,
                    user=User(
                        sub=args.user_sub,
                        given_name=user_given_name,
                        family_name=user_family_name,
                        created_at=user_created_at,
                    ),
                    added_by_user=User(
                        sub=auth_result.result.sub,
                        given_name=added_by_user_given_name,
                        family_name=added_by_user_family_name,
                        created_at=added_by_user_created_at,
                    ),
                    variant=args.variant,
                    display_data=Phone04102023VariantAdmin(
                        phone_number=args.display_data.phone_number,
                        text_prefill=args.display_data.text_prefill,
                        background_image=ImageFileRef(
                            uid=args.display_data.background_image_uid,
                            jwt=await create_image_file_jwt(
                                itgs, args.display_data.background_image_uid
                            ),
                        ),
                        image=ImageFileRef(
                            uid=args.display_data.image_uid,
                            jwt=await create_image_file_jwt(
                                itgs, args.display_data.image_uid
                            ),
                        ),
                        image_caption=args.display_data.image_caption,
                        title=args.display_data.title,
                        message=args.display_data.message,
                        cta=args.display_data.cta,
                    ),
                    reason=args.reason,
                    created_at=now,
                ).model_dump_json(),
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
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=404,
            )

        return Response(
            content=StandardErrorResponse[ERROR_409_TYPES](
                type="user_has_pending_request",
                message="The user already has a pending vip chat request",
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=409,
        )
