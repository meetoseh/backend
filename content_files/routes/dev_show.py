from fastapi.responses import Response
from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import Literal
from itgs import Itgs
from models import (
    AUTHORIZATION_UNKNOWN_TOKEN,
    STANDARD_ERRORS_BY_CODE,
    StandardErrorResponse,
)
import content_files.auth
import os

router = APIRouter()


class DevShowContentFileResponse(BaseModel):
    uid: str = Field(description="The UID of the content file")
    jwt: str = Field(description="The JWT to use to access the content file")


ERROR_404_TYPE = Literal["not_found"]


@router.get(
    "/dev_show/{uid}",
    response_model=DevShowContentFileResponse,
    responses={
        "404": {
            "description": "there is no content file with that uid",
            "model": StandardErrorResponse[ERROR_404_TYPE],
        },
        "403": STANDARD_ERRORS_BY_CODE["403"],
    },
)
async def dev_show_content_file(uid: str):
    """Returns a reference to the content file with the given uid. This endpoint only works in development."""
    if os.environ["ENVIRONMENT"] != "dev":
        return AUTHORIZATION_UNKNOWN_TOKEN

    async with Itgs() as itgs:
        conn = await itgs.conn()
        cursor = conn.cursor("none")

        response = await cursor.execute(
            "SELECT 1 FROM content_files WHERE uid=?", (uid,)
        )
        if not response.results:
            return Response(
                content=StandardErrorResponse[ERROR_404_TYPE](
                    type="not_found", message="There is no content file with that uid"
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=404,
            )

        jwt = await content_files.auth.create_jwt(itgs, uid)
        return Response(
            content=DevShowContentFileResponse(uid=uid, jwt=jwt).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=200,
        )
