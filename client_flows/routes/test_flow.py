from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Annotated, Literal, Optional
from auth import auth_admin
from lib.client_flows.executor import TrustedTrigger, execute_peek
from lib.client_flows.flow_cache import get_client_flow
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from itgs import Itgs
from jsonschema.exceptions import best_match

router = APIRouter()


class TestFlowRequest(BaseModel):
    slug: str = Field(description="The slug of the client flow to test")
    client_parameters: dict = Field(
        description="The client parameters to trigger the flow with"
    )
    server_parameters: dict = Field(
        description="The server parameters to trigger the flow with"
    )
    dry_run: bool = Field(
        False,
        description="If True, the flow is not actually triggered, but the parameters are still validated",
    )


ERROR_404_TYPES = Literal["client_flow_not_found"]

ERROR_409_TYPES = Literal["client_parameters_mismatch", "server_parameters_mismatch"]


@router.post(
    "/test_flow",
    status_code=202,
    responses={
        "404": {
            "description": "The client flow with the given slug was not found",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        "409": {
            "description": "The client or server parameters do not match the flow schema",
            "model": StandardErrorResponse[ERROR_409_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def test_client_flow(
    args: TestFlowRequest, authorization: Annotated[Optional[str], Header()] = None
):
    """Triggers the client flow with the given slug with the given client and
    server parameters.

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        flow = await get_client_flow(itgs, slug=args.slug)
        if flow is None:
            return Response(
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="client_flow_not_found",
                    message="The client flow with the given slug was not found",
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=404,
            )

        err = best_match(flow.client_schema.iter_errors(args.client_parameters))
        if err is not None:
            return Response(
                content=StandardErrorResponse[ERROR_409_TYPES](
                    type="client_parameters_mismatch", message=str(err)
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=409,
            )

        err = best_match(flow.server_schema.iter_errors(args.server_parameters))
        if err is not None:
            return Response(
                content=StandardErrorResponse[ERROR_409_TYPES](
                    type="server_parameters_mismatch", message=str(err)
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=409,
            )

        if args.dry_run:
            return Response(status_code=202)

        await execute_peek(
            itgs,
            user_sub=auth_result.result.sub,
            platform="server",
            trigger=TrustedTrigger(
                flow_slug=flow.slug,
                client_parameters=args.client_parameters,
                server_parameters=args.server_parameters,
            ),
        )
        return Response(status_code=202)
