import os
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, StringConstraints
from typing import Annotated, Optional
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from oauth.models.oauth_state import OauthState
from oauth.routes.prepare import (
    ERROR_409_TYPES,
    INVALID_REDIRECT_URI_RESPONSE,
    associate_state_secret_with_info,
    generate_nonce,
    generate_state_secret,
    get_initial_redirect_uri_for_provider,
    get_provider_url,
    valid_redirect_uris,
    OauthPrepareResponse,
)
from auth import auth_id
from itgs import Itgs
from users.me.routes.read_merge_account_suggestions import MergeProvider


router = APIRouter()


class OauthPrepareForMergeRequest(BaseModel):
    provider: MergeProvider = Field(
        description="Which provider to use for authentication"
    )
    redirect_uri: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=5, max_length=65535)
    ] = Field(
        os.environ["ROOT_FRONTEND_URL"],
        description=(
            "If specified, the url to redirect to after the exchange. This must be "
            "an allowed URL or URL format. We allow the following urls:\n\n"
            "- ROOT_FRONTEND_URL (typically https://oseh.io)\n"
            "- oseh://login_callback\n\n"
        ),
        alias="redirectUrl",  # 1.1.4-1.1.5 of the app accidentally used this name
    )


@router.post(
    "/prepare_for_merge",
    response_model=OauthPrepareResponse,
    responses={
        "409": {
            "description": "The redirect_uri is invalid",
            "model": StandardErrorResponse[ERROR_409_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def prepare_for_merge(
    args: OauthPrepareForMergeRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """An authenticated user A can merge their user on the Oseh platform
    with a different user B on the Oseh platform by providing the standard JWT
    for user A to this endpoint, then directing the user to the URL returned by
    this response. When the user logs in to an identity associated with user B,
    they are redirected back to the requested redirect URL, but rather than
    getting an id token for user B, they get a merge_token for user B.

    The frontend can then pass the id token for user A and the merge token for
    user B to /merge/start. If the merge does not require clarification, user
    B will be merged into user A. Otherwise, the frontend will receive the
    questions to ask and a new confirm merge token for user B. After the user
    answers the questions, the id token for user A and the confirm merge token
    for user B can be sent to /merge/confirm to merge user B into user A.

    Since merging is a nearly symmetrical operation (less minor details like
    exact dates of favoriting content), it's not important which is user A and
    which is user B. However, this may be slightly faster if user A is the
    older account.

    Requires an id token authorization for user A
    """
    async with Itgs() as itgs:
        auth_result = await auth_id(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        if args.redirect_uri not in valid_redirect_uris:
            return INVALID_REDIRECT_URI_RESPONSE

        url = await prepare_user_for_merge(
            itgs,
            user_sub=auth_result.result.sub,
            provider=args.provider,
            redirect_uri=args.redirect_uri,
        )
        return Response(
            content=OauthPrepareResponse(url=url).model_dump_json(),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
            status_code=200,
        )


async def prepare_user_for_merge(
    itgs: Itgs, /, *, user_sub: str, provider: MergeProvider, redirect_uri: str
) -> str:
    if provider == "Dev":
        return os.environ["ROOT_FRONTEND_URL"] + "/dev_login?merge=1"

    state = generate_state_secret()
    nonce = generate_nonce()
    initial_redirect_uri = get_initial_redirect_uri_for_provider(provider)
    url = get_provider_url(
        provider,
        state=state,
        nonce=nonce,
        initial_redirect_uri=initial_redirect_uri,
    )

    await associate_state_secret_with_info(
        itgs,
        secret=state,
        info=OauthState(
            provider=provider,
            refresh_token_desired=False,
            redirect_uri=redirect_uri,
            initial_redirect_uri=initial_redirect_uri,
            nonce=nonce,
            merging_with_user_sub=user_sub,
        ),
    )
    return url
