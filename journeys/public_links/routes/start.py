import secrets
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from typing import AsyncIterator, Literal, Optional, Union
from journeys.lib.notifs import on_entering_lobby
from journeys.lib.read_one_external import read_one_external
from journeys.models.external_journey import ExternalJourney
from journeys.auth import create_jwt as create_journey_jwt
from auth import auth_any
from visitors.lib.get_or_create_visitor import (
    VisitorSource,
    get_or_create_unsanitized_visitor,
)
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from itgs import Itgs

router = APIRouter()


class StartJourneyPublicLinkRequest(BaseModel):
    code: str = Field(
        description="The code included within the public link. This is used to identify the journey."
    )
    source: VisitorSource = Field(
        description="The client used to access the public link"
    )


class StartJourneyPublicLinkResponse(BaseModel):
    journey: ExternalJourney = Field(description="The reference to the journey")
    visitor_uid: str = Field(
        description="The visitor uid that the client should use moving forward"
    )


ERROR_404_TYPES = Literal["invalid_code"]
INVALID_CODE_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="invalid_code",
        message="There is no journey public link with the provided code; it may have been deleted.",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=404,
)


ERROR_503_TYPES = Literal["failed_to_store_view"]
FAILED_TO_STORE_VIEW_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_503_TYPES](
        type="failed_to_store_view",
        message="An error occurred connecting to our database. Please try again later.",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8", "Retry-After": "5"},
    status_code=503,
)


async def _buffered_yield(inner: AsyncIterator[Union[bytes, str]]):
    buffer = b""
    async for chunk in inner:
        buffer += (
            chunk
            if isinstance(chunk, (bytes, bytearray, memoryview))
            else chunk.encode("utf-8")
        )
        if len(buffer) > 8192:
            yield buffer
            buffer = b""
    if len(buffer) > 0:
        yield buffer


async def _yield_response_from_nested(journey: Response, visitor_uid: str):
    """Yields the jsonified bytes response, where the journey is already encoded.
    This can be much more efficient than deserializing and reserializing the journey.
    """
    yield b'{"journey":'
    if isinstance(journey, StreamingResponse):
        async for chunk in journey.body_iterator:
            yield chunk
    else:
        yield journey.body
    yield b',"visitor_uid":"'
    yield visitor_uid.encode("utf-8")
    yield b'"}'


@router.post(
    "/start",
    response_model=StartJourneyPublicLinkResponse,
    responses={
        "404": {
            "description": "There is no journey public link with the provided code; it may have been deleted.",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def start_journey_from_public_link(
    args: StartJourneyPublicLinkRequest,
    authorization: Optional[str] = Header(None),
    visitor: Optional[str] = Header(None),
):
    """Starts a journey using a code provided in the journeys public link.
    If the user is not authorized, they will not be able to start the interactive
    prompt, but they can used the returned reference to watch the class.

    The visitor uid should be provided if available. Standard authorization should
    also be provided, if available.
    """
    async with Itgs() as itgs:
        if authorization is None:
            auth_result = None
        else:
            auth_result = await auth_any(itgs, authorization)
            if auth_result.result is None:
                return auth_result.error_response

        now = time.time()
        visitor_uid = await get_or_create_unsanitized_visitor(
            itgs, visitor=visitor, source=args.source, seen_at=now
        )

        conn = await itgs.conn()
        cursor = conn.cursor("none")

        response = await cursor.execute(
            """
            SELECT
                journeys.uid
            FROM journeys
            WHERE
                EXISTS (
                    SELECT 1 FROM journey_public_links
                    WHERE
                        journey_public_links.code = ?
                        AND journey_public_links.deleted_at IS NULL
                        AND journey_public_links.journey_id = journeys.id
                )
                AND journeys.deleted_at IS NULL
            """,
            (args.code,),
        )
        if not response.results:
            return INVALID_CODE_RESPONSE

        journey_uid = response.results[0][0]

        for attempt in range(2):
            if attempt == 1:
                visitor_uid = await get_or_create_unsanitized_visitor(
                    itgs, visitor=None, source=args.source, seen_at=now
                )

            view_uid = f"oseh_jplv_{secrets.token_urlsafe(16)}"
            response = await cursor.execute(
                """
                INSERT INTO journey_public_link_views (
                    uid, journey_public_link_id, visitor_id, user_id, created_at
                )
                SELECT
                    ?, journey_public_links.id, visitors.id, users.id, ?
                FROM journey_public_links
                JOIN visitors ON visitors.uid = ?
                LEFT OUTER JOIN users ON users.sub = ?
                WHERE
                    journey_public_links.code = ?
                    AND journey_public_links.deleted_at IS NULL
                """,
                (
                    view_uid,
                    now,
                    visitor_uid,
                    (
                        auth_result.result.sub
                        if auth_result is not None and auth_result.result is not None
                        else None
                    ),
                    args.code,
                ),
            )
            if response.rows_affected is not None and response.rows_affected >= 1:
                break
        else:
            return FAILED_TO_STORE_VIEW_RESPONSE

        journey_jwt = await create_journey_jwt(itgs, journey_uid=journey_uid)
        journey = await read_one_external(
            itgs, journey_uid=journey_uid, jwt=journey_jwt
        )
        if journey is None:
            return INVALID_CODE_RESPONSE

        if auth_result is not None and auth_result.result is not None:
            await on_entering_lobby(
                itgs,
                user_sub=auth_result.result.sub,
                journey_uid=journey_uid,
                action=f"viewing public link {args.code}",
            )

        return StreamingResponse(
            content=_buffered_yield(_yield_response_from_nested(journey, visitor_uid)),
            headers={
                "Content-Type": "application/json; charset=utf-8",
            },
            status_code=200,
        )
