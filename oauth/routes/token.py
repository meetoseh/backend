import json
import time
from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field, ValidationError
from typing import Any, Dict, Generic, List, Literal, Optional, TypeVar, Union
from typing_extensions import TypedDict
from urllib.parse import parse_qs
from itgs import Itgs
import os
import timing_attacks
import jwt
from oauth.lib.clients import check_client

router = APIRouter()


class OauthTokenRequest(BaseModel):
    code: str = Field(
        description=(
            "Obtained from the authorization endpoint (https://oseh.io/authorize), represents "
            "the consent given by the end-user"
        ),
    )
    client_id: str = Field(
        description="The client id of the application making the request",
    )
    client_secret: str = Field(
        description="The client secret of the application making the request",
    )
    redirect_uri: str = Field(
        description=(
            "The endpoint that the user landed on with the code. Must be an absolute "
            "URI and must match the redirect URI used to obtain the code, which may "
            "contain query parameters. Prevents certain categories of request forgery."
        )
    )
    grant_type: Literal["authorization_code"] = Field(
        description="The grant type of the request, must be 'authorization_code'",
    )


class OauthTokenResponse(BaseModel):
    id_token: str = Field(
        description=(
            "The JWT containing the user's identity. Contains the claims `sub`, "
            "`email`, `email_verified`, `iat`, `exp` (typically 1m), `iss` "
            "(`oseh-direct-account`), and `aud` (client id)."
        ),
    )


TypeT = TypeVar("TypeT")


# COPIED FROM pydantic-core to extend from typing_extensions
class ErrorDetails(TypedDict):
    type: str
    """
    The type of error that occurred, this is an identifier designed for
    programmatic use that will change rarely or never.

    `type` is unique for each error message, and can hence be used as an identifier to build custom error messages.
    """
    loc: List[Union[int, str]]
    """Tuple of strings and ints identifying where in the schema the error occurred."""
    msg: str
    """A human readable error message."""
    input: Any
    """The input data at this `loc` that caused the error."""
    ctx: Optional[Dict[str, Any]]
    """
    Values which are required to render the error message, and could hence be useful in rendering custom error messages.
    Also useful for passing custom error data forward.
    """


class OauthTokenErrorResponse(BaseModel, Generic[TypeT]):
    error: TypeT = Field(
        description="The error code, see https://connect2id.com/products/server/docs/api/token#token-error",
    )
    error_description: str = Field(
        description="Provides additional information about the error that occurred"
    )
    error_uri: str = Field(
        description="A URI identifying a human-readable web page with information about the error"
    )
    errors: Optional[List[ErrorDetails]] = Field(
        None, description="If validation errors are present, they will be returned here"
    )


ERROR_400_TYPES = Literal["invalid_grant", "invalid_request"]
WRONG_CONTENT_TYPE_RESPONSE = Response(
    content=OauthTokenErrorResponse[ERROR_400_TYPES](
        error="invalid_request",
        error_description="Bad request: Invalid Content-Type (expected application/x-www-form-urlencoded)",
        error_uri="https://datatracker.ietf.org/doc/html/rfc6749#section-5.2",
        errors=None,
    ).model_dump_json(),
    headers={
        "Content-Type": "application/json; charset=utf-8",
    },
    status_code=400,
)

NOT_UTF8_RESPONSE = Response(
    content=OauthTokenErrorResponse[ERROR_400_TYPES](
        error="invalid_request",
        error_description="Bad request: Failed to parse as utf-8",
        error_uri="https://datatracker.ietf.org/doc/html/rfc6749#section-5.2",
        errors=None,
    ).model_dump_json(),
    headers={
        "Content-Type": "application/json; charset=utf-8",
    },
    status_code=400,
)

NOT_URLENCODED_RESPONSE = Response(
    content=OauthTokenErrorResponse[ERROR_400_TYPES](
        error="invalid_request",
        error_description="Bad request: Failed to interpret as application/x-www-form-urlencoded",
        error_uri="https://datatracker.ietf.org/doc/html/rfc6749#section-5.2",
        errors=None,
    ).model_dump_json(),
    headers={
        "Content-Type": "application/json; charset=utf-8",
    },
    status_code=400,
)

INVALID_GRANT_RESPONSE = Response(
    content=OauthTokenErrorResponse[ERROR_400_TYPES](
        error="invalid_grant",
        error_description="Bad request: Invalid or expired authorization code",
        error_uri="https://datatracker.ietf.org/doc/html/rfc6749#section-5.2",
        errors=None,
    ).model_dump_json(),
    headers={
        "Content-Type": "application/json; charset=utf-8",
    },
    status_code=400,
)

ERROR_401_TYPES = Literal["invalid_client"]
INVALID_CLIENT_RESPONSE = Response(
    content=OauthTokenErrorResponse[ERROR_401_TYPES](
        error="invalid_client",
        error_description=(
            "Invalid client: The client_id is missing or invalid, or the "
            "client secret is missing, invalid, or expired, or the client_secret "
            "does not match the client_id"
        ),
        error_uri="https://datatracker.ietf.org/doc/html/rfc6749#section-5.2",
        errors=None,
    ).model_dump_json(),
    headers={
        "Content-Type": "application/json; charset=utf-8",
    },
    status_code=401,
)

ERROR_500_TYPES = Literal["server_error"]
SERVER_ERROR_RESPONSE = Response(
    content=OauthTokenErrorResponse[ERROR_500_TYPES](
        error="server_error",
        error_description="Internal server error: An unexpected error occurred that prevented the server from fulfilling the request",
        error_uri="https://oseh.io/status",
        errors=None,
    ).model_dump_json(),
    headers={
        "Content-Type": "application/json; charset=utf-8",
    },
    status_code=500,
)


@router.post(
    "/token",
    response_model=OauthTokenResponse,
    openapi_extra={
        "requestBody": {
            "content": {
                "application/x-www-form-urlencoded": {
                    "schema": OauthTokenRequest.model_json_schema(),
                }
            }
        },
    },
    responses={
        "400": {
            "description": "Bad Request",
            "model": OauthTokenErrorResponse[ERROR_400_TYPES],
        },
        "401": {
            "description": "Unauthorized Request",
            "model": OauthTokenErrorResponse[ERROR_401_TYPES],
        },
    },
)
async def oauth_token(raw_request: Request):
    """The token endpoint for the OAuth2 flow when using an Oseh direct account.
    Only the `code` flow is supported, and this is currently only used internally,
    so there is no way to register new client ids.
    """
    if raw_request.headers.get("Content-Type") != "application/x-www-form-urlencoded":
        return WRONG_CONTENT_TYPE_RESPONSE

    data = await raw_request.body()
    try:
        decoded_data = data.decode("utf-8")
    except:
        return NOT_UTF8_RESPONSE

    try:
        parsed_data = parse_qs(decoded_data, strict_parsing=True, max_num_fields=100)
    except:
        return NOT_URLENCODED_RESPONSE

    converted_single_values_d = dict(
        (key, value[0] if len(value) == 1 else value)
        for key, value in parsed_data.items()
    )

    try:
        request = OauthTokenRequest.model_validate(converted_single_values_d)
    except ValidationError as e:
        return Response(
            content=OauthTokenErrorResponse[ERROR_400_TYPES](
                error="invalid_request",
                error_description=f"Bad request: unprocessable content",
                error_uri="https://datatracker.ietf.org/doc/html/rfc6749#section-5.2",
                errors=e.errors(),  # type: ignore
            ).model_dump_json(),
            headers={
                "Content-Type": "application/json; charset=utf-8",
            },
            status_code=400,
        )
    except:
        return NOT_URLENCODED_RESPONSE

    if len(request.code) != 22:
        return INVALID_GRANT_RESPONSE

    async with Itgs() as itgs:
        if not await check_client(
            itgs,
            client_id=request.client_id,
            client_secret=request.client_secret,
            redirect_uri=request.redirect_uri,
        ):
            return INVALID_CLIENT_RESPONSE

        redis = await itgs.redis()
        async with timing_attacks.coarsen_time_with_sleeps(0.1):
            code_data = await redis.getdel(
                f"oauth:direct_account:code:{request.client_id}:{request.code}".encode(
                    "utf-8"
                )
            )
            parsed_code_data: Optional[dict] = (
                json.loads(code_data) if code_data is not None else None
            )

    if parsed_code_data is None:
        return INVALID_GRANT_RESPONSE

    if parsed_code_data["expires_at"] < time.time():
        return INVALID_GRANT_RESPONSE

    iat = int(time.time())
    id_token = jwt.encode(
        {
            "sub": parsed_code_data["sub"],
            "email": parsed_code_data["email"],
            "email_verified": parsed_code_data["email_verified"],
            "iss": "oseh-direct-account",
            "aud": request.client_id,
            "iat": iat - 1,
            "exp": iat + 59,
        },
        os.environ["OSEH_DIRECT_ACCOUNT_JWT_SECRET"],
        algorithm="HS256",
    )
    return Response(
        content=OauthTokenResponse(id_token=id_token).model_dump_json(),
        headers={
            "Content-Type": "application/json; charset=utf-8",
        },
        status_code=200,
    )
