from fastapi.responses import Response
from fastapi import APIRouter, Header
from pydantic import BaseModel, Field
from typing import Literal, Optional
from auth import auth_any
from itgs import Itgs
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
import image_files.auth

router = APIRouter()


class ShowMyPictureResponse(BaseModel):
    uid: str = Field(
        description="The UID of the image file for the users profile picture"
    )
    jwt: str = Field(description="The JWT to use to access the image file")


ERROR_404_TYPE = Literal["not_found", "not_available"]


@router.get(
    "/picture",
    response_model=ShowMyPictureResponse,
    responses={
        "404": {
            "description": (
                "the user does not have a profile picture, or it hasnt been processed yet. "
                "Uses not_available if its definitely not processing.",
            ),
            "model": StandardErrorResponse[ERROR_404_TYPE],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def show_my_picture(authorization: Optional[str] = Header(None)):
    """Returns the image file corresponding to the authorized users profile picture.
    This is generally the same image as in the picture claim on the users JWT, however,
    it provides more exports.

    If the user does not have a profile picture, or it has not been processed yet, this
    endpoint will return a 404 error.

    This requires authentication. You can read more about the forms of
    authentication at [/rest_auth.html](/rest_auth.html)
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor("none")

        response = await cursor.execute(
            """
            SELECT
                image_files.uid
            FROM image_files, users, user_profile_pictures
            WHERE
                users.sub = ?
                AND user_profile_pictures.user_id = users.id
                AND user_profile_pictures.latest = 1
                AND image_files.id = user_profile_pictures.image_file_id
            """,
            (auth_result.result.sub,),
        )
        if not response.results:
            redis = await itgs.redis()
            result = await redis.get(
                f"users:{auth_result.result.sub}:checking_profile_image".encode("utf-8")
            )
            if result is None:
                return Response(
                    content=StandardErrorResponse[ERROR_404_TYPE](
                        type="not_available",
                        message="you do not have a profile picture",
                    ).model_dump_json(),
                    headers={"Content-Type": "application/json; charset=utf-8"},
                    status_code=404,
                )

            return Response(
                content=StandardErrorResponse[ERROR_404_TYPE](
                    type="not_found",
                    message="you do not have a profile picture, or it hasn't been processed yet",
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=404,
            )

        image_file_uid: str = response.results[0][0]
        jwt = await image_files.auth.create_jwt(itgs, image_file_uid)
        return Response(
            content=ShowMyPictureResponse(
                uid=image_file_uid, jwt=jwt
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=200,
        )
