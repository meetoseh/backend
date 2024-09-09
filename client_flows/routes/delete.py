from fastapi import APIRouter, Header
from fastapi.responses import Response
from typing import Annotated, Optional, Literal, cast
from itgs import Itgs
from lib.client_flows.flow_cache import (
    purge_client_flow_cache,
    purge_valid_client_flows_cache,
)
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from auth import auth_admin
import lib.client_flows.analysis


router = APIRouter()

ERROR_404_TYPES = Literal["client_flow_not_found"]
ERROR_NOT_FOUND_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="client_flow_not_found",
        message="No client flow with the given UID exists",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=404,
)


@router.delete(
    "/{uid}",
    status_code=204,
    responses={
        "404": {
            "description": "No client flow with the given UID exists",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def delete_client_flow(
    uid: str,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Deletes the client flow with the given UID

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor()
        response = await cursor.executeunified3(
            (
                (
                    "SELECT slug FROM client_flows WHERE uid = ?",
                    (uid,),
                ),
                ("DELETE FROM client_flows WHERE uid = ?", (uid,)),
            )
        )
        if not response[0].results:
            assert response[1].rows_affected is None or response[1].rows_affected < 1
            return ERROR_NOT_FOUND_RESPONSE
        assert response[1].rows_affected == 1
        slug = cast(str, response[0].results[0][0])
        await purge_client_flow_cache(itgs, slug=slug)
        await purge_valid_client_flows_cache(itgs)
        await lib.client_flows.analysis.evict(itgs)
        return Response(status_code=204)
