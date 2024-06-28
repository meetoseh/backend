import os
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Annotated, Literal, Optional, cast
from auth import auth_admin
from lib.client_flows.executor import TrustedTrigger, execute_peek
from lib.client_flows.flow_cache import get_client_flow
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from itgs import Itgs
from jsonschema.exceptions import best_match

from resources.filter import flattened_filters
from resources.filter_item_like import FilterItemLike
from resources.sort_dir import SortDir
from resources.sort_item import SortItem
from users.routes.read import UserFilter, raw_read_users

router = APIRouter()


class OneoffFlowRequest(BaseModel):
    slug: str = Field(
        description="The slug of the client flow to trigger on everyone meeting the criteria"
    )
    client_parameters: dict = Field(
        description="The client parameters to trigger the flow with"
    )
    server_parameters: dict = Field(
        description="The server parameters to trigger the flow with"
    )
    filters: UserFilter = Field(
        default_factory=lambda: UserFilter.model_validate({}),
        description="the filters to apply",
    )


ERROR_404_TYPES = Literal["client_flow_not_found"]
ERROR_409_TYPES = Literal["client_parameters_mismatch", "server_parameters_mismatch"]


@router.post(
    "/oneoff_flow",
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
    args: OneoffFlowRequest, authorization: Annotated[Optional[str], Header()] = None
):
    """Triggers the given client flow on all users matching the filters.

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

        sub_sort = SortItem[Literal["sub"], str](
            key="sub", dir=SortDir.ASCENDING, before=None, after=None
        )

        is_dev = os.environ["ENVIRONMENT"] == "dev"

        slack = await itgs.slack()
        await slack.send_ops_message(
            f"{'[DEV ENVIRONMENT] ' if is_dev else ''}Starting oneoff flow: `{args.slug}` using filters:\n\n```\n{args.filters.model_dump_json(indent=2)}\n```\n"
        )

        filters_to_apply = flattened_filters(
            dict(
                (k, cast(FilterItemLike, v.to_result()))
                for k, v in args.filters.__dict__.items()
                if v is not None
            )
        )

        batch_size = 100
        started_at = time.time()
        progress_report_interval_seconds = 10

        users_so_far = 0
        last_reported_progress_at = started_at
        last_reported_users_so_far = 0

        while True:
            batch = await raw_read_users(
                itgs,
                filters_to_apply=filters_to_apply,
                sort=[sub_sort],
                limit=batch_size,
            )

            if not batch:
                break

            for user in batch:
                await execute_peek(
                    itgs,
                    user_sub=user.sub,
                    platform="server",
                    trigger=TrustedTrigger(
                        flow_slug=flow.slug,
                        client_parameters=args.client_parameters,
                        server_parameters=args.server_parameters,
                    ),
                )
                users_so_far += 1

                time_now = time.time()
                if (
                    time_now - last_reported_progress_at
                    > progress_report_interval_seconds
                ):
                    overall_time_elapsed = time_now - started_at
                    await slack.send_ops_message(
                        f"{'[DEV ENVIRONMENT] ' if is_dev else ''}Progress on `{args.slug}` one off trigger: {users_so_far} users processed so far\n"
                        f"- time elapsed: {overall_time_elapsed:.1f} seconds\n"
                        f"- rate overall: {users_so_far / overall_time_elapsed if overall_time_elapsed > 1e-6 else 0:.1f} users per second\n"
                        f"- rate recent: {(users_so_far - last_reported_users_so_far) / (time_now - last_reported_progress_at) if time_now - last_reported_progress_at > 1e-6 else 0:.1f} users per second\n"
                    )
                    last_reported_progress_at = time_now
                    last_reported_users_so_far = users_so_far

            sub_sort.after = batch[-1].sub

        ended_at = time.time()
        overall_time_elapsed = ended_at - started_at
        await slack.send_ops_message(
            f"{'[DEV ENVIRONMENT] ' if is_dev else ''}Finished `{args.slug}` one off trigger: {users_so_far} users processed in {overall_time_elapsed:.1f} seconds"
        )
        if not is_dev:
            await slack.send_oseh_bot_message(
                f"Triggered the `{args.slug}` flow on {users_so_far} users in {overall_time_elapsed:.1f} seconds ({users_so_far / overall_time_elapsed if overall_time_elapsed > 1e-6 else 0:.1f} users per second). Filters:\n\n```\n{args.filters.model_dump_json(indent=2)}\n```\n"
            )
