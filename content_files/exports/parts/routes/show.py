from typing import Literal, Optional
from fastapi import APIRouter, Header
from fastapi.responses import Response
from models import (
    STANDARD_ERRORS_BY_CODE,
    StandardErrorResponse,
    AUTHORIZATION_UNKNOWN_TOKEN,
)
import content_files.auth
import content_files.helper
from itgs import Itgs


ERROR_404_TYPES = Literal["not_found"]

router = APIRouter()


@router.get(
    "/{uid}.{ext}",
    responses={
        "404": {
            "description": "the content file export part with that uid does not exist; it may still be processing or have been deleted",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def get_content_file_export_part(
    uid: str,
    ext: str,
    jwt: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """Gets the content file export part with the given uid. The extension provided is
    ignored, but the content-type of the response is set to the correct type.

    The result will have the appropriate content type based on the actual file type.

    Either the `jwt` query parameter or the `authorization` header must be set. If
    both are set, the `jwt` is ignored. This is not a standard JWT - it must be a
    JWT that is specific to the content file the export part is for.
    """
    token: Optional[str] = None
    if authorization is not None:
        token = authorization
    elif jwt is not None:
        token = f"bearer {jwt}"

    del authorization
    del jwt

    async with Itgs() as itgs:
        auth_result = await content_files.auth.auth_any(itgs, token)
        if auth_result.result is None:
            return auth_result.error_response

        meta = await content_files.helper.get_cfep_metadata(itgs, uid)
        if meta is None:
            return Response(
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="not_found",
                    message=(
                        "the content file export part with that uid does not exist; it may "
                        "still be processing or have been deleted"
                    ),
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=404,
            )

        if meta.content_file_uid != auth_result.result.content_file_uid:
            return AUTHORIZATION_UNKNOWN_TOKEN

        return await content_files.helper.serve_cfep(itgs, meta)
