import secrets
from typing import Literal, Optional
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from auth import auth_any as std_auth_any
from journeys.auth import auth_any as journey_auth_any
from interactive_prompts.auth import create_jwt as create_interactive_prompt_jwt
from interactive_prompts.models.external_interactive_prompt import (
    ExternalInteractivePrompt,
)
from interactive_prompts.lib.read_one_external import read_one_external
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse, ERROR_403_TYPE
from itgs import Itgs


class StartInteractivePromptRequest(BaseModel):
    journey_uid: str = Field(
        description=(
            "The UID of the journey to start the interactive prompt in. This "
            "must match the sub of the journey jwt provided"
        )
    )

    journey_jwt: str = Field(
        description=(
            "The JWT which proves you have access to start the interactive prompt "
            "within the journey. Not prefixed with anything"
        )
    )


router = APIRouter()

ERROR_503_TYPES = Literal["journey_gone", "session_failed_to_start"]


@router.post(
    "/start_interactive_prompt",
    status_code=201,
    response_model=ExternalInteractivePrompt,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def start_journeys_interactive_prompt(
    args: StartInteractivePromptRequest, authorization: Optional[str] = Header(None)
):
    """Uses a journey JWT to create a new session within the interactive
    prompt for the journey as well as return the information on, and a
    JWT for, the interactive prompt used in the lobby of the journey.

    Requires standard authorization in addition to the journey JWT as
    the session is attached to both the user and the journey.
    """
    async with Itgs() as itgs:
        std_auth_result = await std_auth_any(itgs, authorization)
        if not std_auth_result.success:
            return std_auth_result.error_response

        journey_auth_result = await journey_auth_any(itgs, f"bearer {args.journey_jwt}")
        if not journey_auth_result.success:
            return journey_auth_result.error_response

        if journey_auth_result.result.journey_uid != args.journey_uid:
            return Response(
                status_code=403,
                content=StandardErrorResponse[ERROR_403_TYPE](
                    type="invalid",
                    message=(
                        "Although the provided journey JWT is valid, it is not "
                        "for the journey specified in the request body. You may "
                        "have a token mixup; to help debug, recall that the claims in "
                        "the JWT are not encrypted, so e.g., https://jwt.io can be used to "
                        "check which token you have."
                    ),
                ).json(),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                },
            )

        conn = await itgs.conn()
        cursor = conn.cursor("none")

        response = await cursor.execute(
            """
            SELECT uid FROM interactive_prompts
            WHERE
                EXISTS (
                    SELECT 1 FROM journeys
                    WHERE journeys.uid = ?
                        AND journeys.interactive_prompt_id = interactive_prompts.id
                        AND journeys.deleted_at IS NULL
                )
                AND interactive_prompts.deleted_at IS NULL
            """,
            (journey_auth_result.result.journey_uid,),
        )
        if not response.results:
            return Response(
                status_code=503,
                content=StandardErrorResponse[ERROR_503_TYPES](
                    type="journey_gone",
                    message=(
                        "The journey has been modified or deleted. Please try again."
                    ),
                ).json(),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Retry-After": "15",
                },
            )
        interactive_prompt_uid = response.results[0][0]

        session_uid = f"oseh_ips_{secrets.token_urlsafe(16)}"
        response = await cursor.execute(
            """
            INSERT INTO interactive_prompt_sessions (
                interactive_prompt_id, user_id, uid
            )
            SELECT
                interactive_prompts.id, users.id, ?
            FROM interactive_prompts, users
            WHERE
                EXISTS (
                    SELECT 1 FROM journeys
                    WHERE journeys.uid = ? 
                      AND journeys.interactive_prompt_id = interactive_prompts.id
                      AND journeys.deleted_at IS NULL
                )
                AND users.sub = ?
                AND interactive_prompts.deleted_at IS NULL
                AND interactive_prompts.uid = ?
            """,
            (
                session_uid,
                journey_auth_result.result.journey_uid,
                std_auth_result.result.sub,
                interactive_prompt_uid,
            ),
        )
        if response.rows_affected is None or response.rows_affected < 1:
            return Response(
                status_code=503,
                content=StandardErrorResponse[ERROR_503_TYPES](
                    type="session_failed_to_start",
                    message=(
                        "The session failed to start. This could be because the journey "
                        "has been modified or deleted. Please try again."
                    ),
                ).json(),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Retry-After": "15",
                },
            )

        prompt_jwt = await create_interactive_prompt_jwt(
            itgs, interactive_prompt_uid=interactive_prompt_uid
        )
        result = await read_one_external(
            itgs,
            interactive_prompt_uid=interactive_prompt_uid,
            interactive_prompt_jwt=prompt_jwt,
            interactive_prompt_session_uid=session_uid,
        )
        if result is None:
            return Response(
                status_code=503,
                content=StandardErrorResponse[ERROR_503_TYPES](
                    type="journey_gone",
                    message=(
                        "The journey has been modified or deleted. Please try again."
                    ),
                ).json(),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Retry-After": "15",
                },
            )

        return result
