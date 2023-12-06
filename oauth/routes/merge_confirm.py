import socket
from typing import Annotated, Literal, Optional
from fastapi import APIRouter, Header, Response
from pydantic import BaseModel, Field, StringConstraints
from auth import auth_id
from error_middleware import handle_error
from models import (
    AUTHORIZATION_UNKNOWN_TOKEN,
    STANDARD_ERRORS_BY_CODE,
    StandardErrorResponse,
)
import oauth.lib.merging.confirm_merge_auth as confirm_merge_auth
from oauth.lib.merging.confirm_merge import attempt_confirm_merge
from itgs import Itgs


router = APIRouter()


class OauthMergeConfirmRequest(BaseModel):
    merge_token: str = Field(
        description=("The merge token returned back from the /merge/start endpoint")
    )
    email_hint: Annotated[
        Optional[str],
        StringConstraints(
            min_length=2, max_length=255, strip_whitespace=True, to_lower=True
        ),
    ] = Field(
        None,
        description=(
            "Which email address should stay enabled after the merge from the "
            "choices provided. Must be provided iff requested."
        ),
    )
    phone_hint: Annotated[
        Optional[str],
        StringConstraints(
            min_length=2, max_length=255, strip_whitespace=True, to_lower=True
        ),
    ] = Field(
        None,
        description=(
            "Which phone number should stay enabled after the merge from the "
            "choices provided. Must be provided iff requested."
        ),
    )


ERROR_409_TYPES = Literal["conflict"]
ERROR_503_TYPES = Literal["service_unavailable"]


@router.post(
    "/merge/confirm",
    status_code=204,
    responses={
        **STANDARD_ERRORS_BY_CODE,
        "409": {
            "model": StandardErrorResponse[ERROR_409_TYPES],
            "description": (
                "The email or phone hint was not provided when requested, "
                "or was provided when not requested, or was not one of the "
                "options provided."
            ),
        },
    },
)
async def merge_confirm(
    args: OauthMergeConfirmRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Uses the given disambiguation information to merge user B identified
    by the merge token into user A from the authorization header

    Requires an id token authorization for user A.
    """
    async with Itgs() as itgs:
        std_auth_result = await auth_id(itgs, authorization)
        if std_auth_result.result is None:
            return std_auth_result.error_response

        confirm_merge_auth_result = await confirm_merge_auth.auth_presigned(
            itgs, args.merge_token, no_prefix=True
        )
        if confirm_merge_auth_result.result is None:
            return confirm_merge_auth_result.error_response

        if (
            std_auth_result.result.sub
            != confirm_merge_auth_result.result.original_user_sub
        ):
            return AUTHORIZATION_UNKNOWN_TOKEN

        if confirm_merge_auth_result.result.conflicts.email is not (
            args.email_hint is not None
        ):
            return Response(
                status_code=409,
                content=StandardErrorResponse[ERROR_409_TYPES](
                    type="conflict",
                    message=(
                        "The email hint was not provided when requested"
                        if args.email_hint is None
                        else "The email hint was provided when not requested"
                    ),
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        if confirm_merge_auth_result.result.conflicts.phone is not (
            args.phone_hint is not None
        ):
            return Response(
                status_code=409,
                content=StandardErrorResponse[ERROR_409_TYPES](
                    type="conflict",
                    message=(
                        "The phone hint was not provided when requested"
                        if args.phone_hint is None
                        else "The phone hint was provided when not requested"
                    ),
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        try:
            result = await attempt_confirm_merge(
                itgs,
                original_user=std_auth_result.result,
                merge=confirm_merge_auth_result.result,
                email_hint=args.email_hint,
                phone_hint=args.phone_hint,
            )
        except Exception as e:
            await handle_error(
                e,
                extra_info=f"original user sub=`{std_auth_result.result.sub}`, merging user sub=`{confirm_merge_auth_result.result.merging_user_sub}`",
            )
            return Response(
                status_code=503,
                content=StandardErrorResponse[ERROR_503_TYPES](
                    type="service_unavailable",
                    message=(
                        "The email or phone hint may not have been one of the "
                        "available options, or the identity you are trying to "
                        "merge in has changed since you started the merge. "
                        "At best, you can try again from the beginning."
                    ),
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        try:
            slack = await itgs.slack()
            result_str = "success" if result else "failure"
            await slack.send_oseh_bot_message(
                f"`{socket.gethostname()}` Original user `{std_auth_result.result.sub}` just performed "
                f"the confirm account merge step to merge in the identity via provider "
                f"{confirm_merge_auth_result.result.provider} and sub "
                f"`{confirm_merge_auth_result.result.provider_sub}`."
                f"\n\nResult: {result_str}",
                preview=f"Confirm merge {result_str}",
            )
        except Exception as e:
            await handle_error(e)

        if result:
            return Response(status_code=204)

        return AUTHORIZATION_UNKNOWN_TOKEN
