import base64
import gzip
import json
import secrets
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, StringConstraints
from typing import Annotated, Literal, Optional
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from touch_points.lib.etag import get_messages_etag
from touch_points.lib.touch_points import TouchPointMessages
from auth import auth_admin
from itgs import Itgs
from touch_points.routes.read import TouchPointWithMessages

router = APIRouter()


class CreateTouchPointRequest(BaseModel):
    event_slug: Annotated[
        str,
        StringConstraints(
            min_length=2,
            max_length=255,
            strip_whitespace=True,
            pattern=r"^[a-zA-Z][a-zA-Z_]*[a-zA-Z]$",
        ),
    ] = Field(
        description="The slug of the event that triggers this touch point. May carry special meaning.",
    )
    selection_strategy: Literal[
        "random_with_replacement", "fixed", "ordered_resettable"
    ] = Field(
        description="The strategy used to select a message from the messages list. See the db documentation for details.",
    )
    messages: TouchPointMessages = Field(
        description="The messages this touch point can send, selected from according to the selection strategy.",
    )


ERROR_409_TYPES = Literal["event_slug_exists"]
ERROR_EVENT_SLUG_EXISTS_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_409_TYPES](
        type="event_slug_exists",
        message="A touch point with this event slug already exists.",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=409,
)

DEFAULT_SCHEMA = {"type": "object", "additionalProperties": False, "example": {}}


@router.post(
    "/",
    response_model=TouchPointWithMessages,
    responses={
        "409": {
            "description": "A touch point with this event slug already exists.",
            "model": StandardErrorResponse[ERROR_409_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def create_touch_point(
    args: CreateTouchPointRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Creates a new touch point that triggers on the event with the given slug.
    Note that the event slug may have special meaning for customized flows, in
    the sense that it may be directly referenced within the code.

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor("strong")

        uid = f"oseh_tpo_{secrets.token_urlsafe(16)}"
        request_at = time.time()

        messages_raw = base64.b85encode(
            gzip.compress(
                TouchPointMessages.__pydantic_serializer__.to_json(args.messages),
                compresslevel=9,
                mtime=0,
            )
        ).decode("ascii")
        response = await cursor.execute(
            """
INSERT INTO touch_points (
    uid, event_slug, event_schema, selection_strategy, messages, created_at
)
SELECT
    ?, ?, ?, ?, ?, ?
WHERE
    NOT EXISTS (
        SELECT 1 FROM touch_points WHERE event_slug = ?
    )
            """,
            (
                uid,
                args.event_slug,
                json.dumps(DEFAULT_SCHEMA, sort_keys=True),
                args.selection_strategy,
                messages_raw,
                request_at,
                args.event_slug,
            ),
        )

        if response.rows_affected is None or response.rows_affected < 1:
            return ERROR_EVENT_SLUG_EXISTS_RESPONSE
        assert response.rows_affected == 1, args
        return Response(
            content=TouchPointWithMessages(
                uid=uid,
                event_slug=args.event_slug,
                event_schema=DEFAULT_SCHEMA,
                selection_strategy=args.selection_strategy,
                messages=args.messages,
                messages_etag=get_messages_etag(messages_raw),
                created_at=request_at,
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
