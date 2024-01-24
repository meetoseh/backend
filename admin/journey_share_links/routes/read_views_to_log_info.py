from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Annotated, Optional
from models import STANDARD_ERRORS_BY_CODE
from auth import auth_admin
from itgs import Itgs
from redis_helpers.run_with_prep import run_with_prep
from redis_helpers.share_links_view_to_log_info import (
    ensure_share_links_view_to_log_info_script_exists,
    share_links_view_to_log_info,
)


class ReadViewsToLogInfoResponse(BaseModel):
    length: int = Field(description="How many views are in the `views_to_log` list")
    first_clicked_at: Optional[float] = Field(
        description=(
            "If there is at least one item in the list and it has an entry in "
            "the pseudoset, when the first item was clicked at. Gives a sense of "
            "how behind the job is. Specified in seconds since the epoch"
        )
    )
    first_confirmed_at: Optional[float] = Field(
        description=(
            "If there is at least one item in the list and it has an entry in "
            "the pseudoset, and the item is confirmed in the pseudoset, when the "
            "first item was confirmed. Gives a sense of how behind the job is. "
            "Specified in seconds since the epoch"
        )
    )


router = APIRouter()


@router.get(
    "/views_to_log_info",
    response_model=ReadViewsToLogInfoResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_views_to_log_info(
    authorization: Annotated[Optional[str], Header()] = None
):
    """Reads information about the journey share links To Log list

    Requires standard authorization for an admin user
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        redis = await itgs.redis()

        async def _prepare(force: bool):
            await ensure_share_links_view_to_log_info_script_exists(redis, force=force)

        async def _execute():
            return await share_links_view_to_log_info(redis)

        info = await run_with_prep(_prepare, _execute)
        assert info is not None
        return Response(
            content=ReadViewsToLogInfoResponse.__pydantic_serializer__.to_json(
                ReadViewsToLogInfoResponse(
                    length=info.length,
                    first_clicked_at=info.first_clicked_at,
                    first_confirmed_at=info.first_confirmed_at,
                )
            ),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=200,
        )
