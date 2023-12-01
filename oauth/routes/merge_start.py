from typing import Annotated, Optional
from fastapi import APIRouter, Header
from pydantic import BaseModel, Field
from auth import auth_id
from error_middleware import handle_error
from models import STANDARD_ERRORS_BY_CODE
from oauth.lib.merging.start_merge import OauthMergeResult, attempt_start_merge
import oauth.lib.merging.start_merge_auth as start_merge_auth
from itgs import Itgs


router = APIRouter()


class OauthMergeStartRequest(BaseModel):
    merge_token: str = Field(
        description=(
            "The merge token returned back to the client as a "
            "result of an OAuth login flow initiated with /prepare_for_merge"
        )
    )


@router.post(
    "/merge/start", responses=STANDARD_ERRORS_BY_CODE, response_model=OauthMergeResult
)
async def merge_start(
    args: OauthMergeStartRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """When provided with the standard authorization token for user A
    and a merge token for an identity I which might correspond with another
    user, user B, this will handle associating the identity I with user A
    and merging user B with user A, as appropriate.

    Requires an id token authorization for user A.
    """
    async with Itgs() as itgs:
        std_auth_result = await auth_id(itgs, authorization)
        if std_auth_result.result is None:
            return std_auth_result.error_response

        start_merge_auth_result = await start_merge_auth.auth_presigned(
            itgs, args.merge_token, no_prefix=True
        )
        if start_merge_auth_result.result is None:
            return start_merge_auth_result.error_response

        result = await attempt_start_merge(
            itgs,
            original_user=std_auth_result.result,
            merge=start_merge_auth_result.result,
        )

        try:
            slack = await itgs.slack()
            await slack.send_oseh_bot_message(
                f"Original user `{std_auth_result.result.sub}` just performed "
                f"the first account merge step to merge in the identity via provider "
                f"{start_merge_auth_result.result.provider} and sub "
                f"`{start_merge_auth_result.result.provider_sub}`."
                f"\n\nResult: `{result.result}`",
                preview=f"Start merge {result.result}",
            )
        except Exception as e:
            await handle_error(e)

        return result
