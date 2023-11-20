from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal, Optional
from auth import auth_any
from error_middleware import handle_contextless_error
from image_files.models import ImageFileRef
from itgs import Itgs
from models import STANDARD_ERRORS_BY_CODE
from image_files.auth import create_jwt as create_image_jwt
from vip_chat_requests.routes.create import Phone04102023VariantInternal


router = APIRouter()


class Phone04102023Variant(BaseModel):
    identifier: Literal["phone-04102023"] = Field(description="The variant identifier")
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


class ReadVIPChatResponse(BaseModel):
    uid: str = Field(description="The UID of the vip chat request that should be shown")
    variant: Phone04102023Variant = Field(
        description="The variant of the vip chat request"
    )


@router.get(
    "/mine",
    response_model=ReadVIPChatResponse,
    status_code=200,
    responses={
        "204": {"description": "No vip chat request to show"},
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def read_vip_chat_request(
    authorization: Optional[str] = Header(None),
):
    """Some users are particularly notable - they might use the app more than
    most, or in an unusual way, or they might have made an interesting comment
    or mentioned us in social media. When we want them to reach out to them,
    the frontend displays a friendly pop-up asking them to get in touch, and this
    endpoint allows the frontend to determine when and how to show that popup.

    Since we usually show sensitive information, e.g., a founders personal phone
    number, the data is not hard-coded in the frontend.

    Requires standard authorization.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor("none")

        response = await cursor.execute(
            """
            SELECT uid, variant, display_data FROM vip_chat_requests
            WHERE
                EXISTS (
                    SELECT 1 FROM users
                    WHERE users.id = vip_chat_requests.user_id
                      AND users.sub = ?
                )
                AND vip_chat_requests.popup_seen_at IS NULL
            """,
            (auth_result.result.sub,),
        )

        if not response.results:
            return Response(status_code=204)

        uid: str = response.results[0][0]
        variant: str = response.results[0][1]
        display_data: str = response.results[0][2]

        if variant != "phone-04102023":
            await handle_contextless_error(
                extra_info=(
                    f"For {auth_result.result.sub=}, have vip chat request {variant=} which is not supported"
                )
            )
            return Response(status_code=204)

        parsed_display_data = Phone04102023VariantInternal.model_validate_json(
            display_data
        )
        assert parsed_display_data.background_image_uid is not None
        assert parsed_display_data.image_uid is not None
        assert parsed_display_data.phone_number is not None
        assert parsed_display_data.text_prefill is not None
        assert parsed_display_data.image_caption is not None
        assert parsed_display_data.title is not None
        assert parsed_display_data.message is not None
        assert parsed_display_data.cta is not None

        return Response(
            content=ReadVIPChatResponse(
                uid=uid,
                variant=Phone04102023Variant(
                    identifier="phone-04102023",
                    phone_number=parsed_display_data.phone_number,
                    text_prefill=parsed_display_data.text_prefill,
                    background_image=ImageFileRef(
                        uid=parsed_display_data.background_image_uid,
                        jwt=await create_image_jwt(
                            itgs, parsed_display_data.background_image_uid
                        ),
                    ),
                    image=ImageFileRef(
                        uid=parsed_display_data.image_uid,
                        jwt=await create_image_jwt(itgs, parsed_display_data.image_uid),
                    ),
                    image_caption=parsed_display_data.image_caption,
                    title=parsed_display_data.title,
                    message=parsed_display_data.message,
                    cta=parsed_display_data.cta,
                ),
            ).model_dump_json(),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
            status_code=200,
        )
