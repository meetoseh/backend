import json
import secrets
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, StringConstraints
from typing import Annotated, Optional, Literal
from client_flows.lib.parse_flow_screens import encode_flow_screens
from lib.client_flows.client_flow_rule import client_flow_rules_adapter
from itgs import Itgs
from lib.client_flows.flow_cache import purge_client_flow_cache
from lib.client_flows.flow_flags import ClientFlowFlag
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from auth import auth_admin
from client_flows.routes.read import ClientFlow


router = APIRouter()


class CreateClientFlowRequest(BaseModel):
    slug: Annotated[
        str,
        StringConstraints(
            pattern="^[a-z0-9_-]+$",
            min_length=1,
            max_length=255,
            strip_whitespace=True,
        ),
    ] = Field(description="The slug of the new client flow")


ERROR_409_TYPES = Literal["client_flow_slug_exists"]
ERROR_CLIENT_FLOW_SLUG_EXISTS_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_409_TYPES](
        type="client_flow_slug_exists",
        message="A client flow with the given slug already exists",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=409,
)


@router.post(
    "/",
    status_code=201,
    response_model=ClientFlow,
    responses={
        "409": {
            "description": "A client flow with the given slug already exists",
            "model": StandardErrorResponse[ERROR_409_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def create_client_flow(
    args: CreateClientFlowRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Creates a new client flow with the given slug and no client or
    server parameters.

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor("strong")

        flow = ClientFlow(
            uid=f"oseh_cfl_{secrets.token_urlsafe(16)}",
            slug=args.slug,
            name=None,
            description=None,
            client_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
                "example": {},
            },
            server_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
                "example": {},
            },
            replaces=False,
            screens=[],
            rules=[],
            flags=int(
                ClientFlowFlag.SHOWS_IN_ADMIN
                | ClientFlowFlag.IS_CUSTOM
                | ClientFlowFlag.ANDROID_TRIGGERABLE
                | ClientFlowFlag.IOS_TRIGGERABLE
                | ClientFlowFlag.BROWSER_TRIGGERABLE
            ),
            created_at=time.time(),
        )

        response = await cursor.execute(
            """
INSERT INTO client_flows (
    uid, slug, name, description, client_schema, server_schema,
    replaces, screens, rules, flags, created_at
)
SELECT
    ?, ?, NULL, NULL, ?, ?, ?, ?, ?, ?, ?
WHERE
    NOT EXISTS (
        SELECT 1 FROM client_flows AS cf
        WHERE cf.slug = ?
    )
            """,
            (
                flow.uid,
                flow.slug,
                json.dumps(flow.client_schema, sort_keys=True),
                json.dumps(flow.server_schema, sort_keys=True),
                int(flow.replaces),
                encode_flow_screens(flow.screens),
                json.dumps(
                    client_flow_rules_adapter.dump_python(
                        flow.rules, exclude_unset=True
                    ),
                    sort_keys=True,
                ),
                flow.flags,
                flow.created_at,
                flow.slug,
            ),
        )

        if response.rows_affected is None or response.rows_affected <= 0:
            return ERROR_CLIENT_FLOW_SLUG_EXISTS_RESPONSE

        await purge_client_flow_cache(itgs, slug=flow.slug)
        return Response(
            content=ClientFlow.__pydantic_serializer__.to_json(flow),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=201,
        )
