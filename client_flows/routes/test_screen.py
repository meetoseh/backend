import json
import secrets
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from jsonschema import Validator
from pydantic import BaseModel, Field
from typing import Annotated, Any, Dict, List, Optional, Literal, Union, cast
from courses.models.external_course import ExternalCourse
from journeys.models.external_journey import ExternalJourney
from lib.client_flows.client_flow_screen import ClientFlowScreen
from lib.client_flows.flow_cache import ClientFlow, get_client_flow
from lib.client_flows.flow_flags import ClientFlowFlag
from lib.client_flows.helper import (
    FlowScreenRequiredParameter,
    check_oas_30_schema,
    deep_extract,
    extract_from_model_json_schema,
    extract_schema_default_value,
    handle_trigger_time_client_transformations,
    iter_flow_screen_required_parameters,
    pretty_path,
    produce_screen_input_parameters,
    handle_trigger_time_server_transformations,
)
from lib.client_flows.screen_cache import ClientScreen, get_client_screen
from lib.client_flows.screen_schema import UNSAFE_SCREEN_SCHEMA_TYPES, SpecialIndex
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from itgs import Itgs
from auth import auth_admin
from openapi_schema_validator import OAS30Validator
from jsonschema.exceptions import best_match
from dataclasses import dataclass

from user_safe_error import UserSafeError
from users.me.screens.lib.standard_parameters import (
    create_standard_parameters,
    get_requested_standard_parameters,
    get_standard_parameter_schema,
)


class TestClientScreenRequestFlow(BaseModel):
    client_schema: dict = Field(
        description="A valid OpenAPI 3.0.3 schema object representing the client arguments to the flow."
    )
    server_schema: dict = Field(
        description="A valid OpenAPI 3.0.3 schema object representing the server arguments to the flow."
    )


class TestClientScreenRequest(BaseModel):
    flow: TestClientScreenRequestFlow = Field(
        description="The abbreviated client flow within which this client flow screen is to be tested."
    )
    flow_screen: ClientFlowScreen = Field(
        description="The flow screen within the flow that we are prepending"
    )
    client_parameters: dict = Field(
        description="The client parameters that were provided (in this simulation) to the client flow trigger"
    )
    server_parameters: dict = Field(
        description="The server parameters that were provided (in this simulation) to the client flow trigger"
    )
    dry_run: bool = Field(
        False,
        description=(
            "If true, we don't actually prepend the screen. Useful for just checking that "
            "we could have (e.g., schemas are valid, parameters make sense, etc.). When doing "
            "this, its often useful to just take the example for the client schema and the example "
            "for the server schema, as they must be valid for the schemas to be valid"
        ),
    )


router = APIRouter()

ERROR_409_TYPES = Literal[
    "client_schema_invalid",
    "server_schema_invalid",
    "client_parameters_mismatch",
    "server_parameters_mismatch",
    "screen_not_found",
    "screen_is_unsafe",
    "screen_input_parameters_wont_match",
    "screen_input_parameters_redundant",
    "screen_input_parameters_didnt_match",
    "skip",
]


@router.post(
    "/test_screen",
    status_code=202,
    responses={
        "409": {
            "model": StandardErrorResponse[ERROR_409_TYPES],
            "description": (
                """
A flow with these settings, which had a flow screen configured as specified,
could not be triggered with these client and server parameters.

-   `client_schema_invalid`: The flow itself is misconfigured because the `client_schema`
    either isn't a valid OpenAPI 3.0.3 schema or it doesn't have an example that meets its
    own requirements (recursively). All valid client schemas are valid openapi 3.0.3 schemas,
    but only openapi 3.0.3 schemas where `example` is treated as required are valid client
    schemas.

-   `server_schema_invalid`: The flow itself is misconfigured because the `server_schema`
    either isn't a valid OpenAPI 3.0.3 schema or it doesn't have an example that meets its
    own requirements (recursively). All valid server schemas are valid openapi 3.0.3 schemas,
    but only openapi 3.0.3 schemas where `example` is treated as required are valid server
    schemas.

-   `client_parameters_mismatch`: The client parameters provided don't match the client schema
    for the flow.

-   `server_parameters_mismatch`: The server parameters provided don't match the server schema
    for the flow.

-  `screen_not_found`: The screen specified in the flow screen doesn't exist.

-   `screen_is_unsafe`: The screen is unsafe because it has a variable parameter that uses
    either a client parameter or a standard parameter for targetting a screen input parameter
    that requires trusted input 
    (e.g., an parameter with `{"type": "string", "format": "image_uid"}`). You can only fill
    these with either fixed values or exclusively from the server parameters.

-   `screen_input_parameters_wont_match`: Our static analysis was able to determine using only
    the flows client and server schema and the flow screens settings that the screen input
    parameters might not always match the screens schema. Note that this doesn't depend on the
    provided `client_parameters` or `server_parameters`.

-   `screen_input_parameters_redundant`: The screen overwrites a fixed value with a variable
    input; remove the fixed value as it is redundant.

-   `screen_input_parameters_didnt_match`: When using the provided `client_parameters` and 
    `server_parameters` and the flow screens settings, the resulting screen input parameters
    didn't match the screens schema.

-   `skip`: screen would be skipped due to trigger-time variable inputs, e.g., extract with
    `skip_if_missing=True`. This isn't necessarily an issue with the screen, but generally 
    you should be able to come up with parameters that won't result in a skip before saving
    a screen.
                """
            ),
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def test_screen(
    args: TestClientScreenRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Verifies that a flow which has the given flow screen can be triggered with the given
    parameters, and optionally (based on `dry_run`), prepends that screen to the authorized
    users client screen queue.

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        try:
            check_oas_30_schema(args.flow.client_schema, require_example=True)
        except Exception as e:
            return Response(
                status_code=409,
                content=StandardErrorResponse[ERROR_409_TYPES](
                    type="client_schema_invalid",
                    message=str(e),
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        try:
            check_oas_30_schema(args.flow.server_schema, require_example=True)
        except Exception as e:
            return Response(
                status_code=409,
                content=StandardErrorResponse[ERROR_409_TYPES](
                    type="server_schema_invalid",
                    message=str(e),
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        client_schema_validator = cast(
            Validator, OAS30Validator(args.flow.client_schema)
        )
        err = best_match(client_schema_validator.iter_errors(args.client_parameters))
        if err is not None:
            return Response(
                status_code=409,
                content=StandardErrorResponse[ERROR_409_TYPES](
                    type="client_parameters_mismatch",
                    message=str(err),
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        server_schema_validator = cast(
            Validator, OAS30Validator(args.flow.server_schema)
        )
        err = best_match(server_schema_validator.iter_errors(args.server_parameters))
        if err is not None:
            return Response(
                status_code=409,
                content=StandardErrorResponse[ERROR_409_TYPES](
                    type="server_parameters_mismatch",
                    message=str(err),
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        screen = await get_client_screen(itgs, slug=args.flow_screen.screen.slug)
        if screen is None:
            return Response(
                status_code=409,
                content=StandardErrorResponse[ERROR_409_TYPES](
                    type="screen_not_found",
                    message=f"No screen with slug {args.flow_screen.screen.slug}",
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        discriminators: Dict[tuple, int] = dict()
        try:
            for (
                enum_path_with_special_indices,
                allowed_values,
            ) in screen.realizer.iter_enum_discriminators():
                for enum_path in fix_special_enum_path_indices(
                    enum_path_with_special_indices,
                    screen.raw_schema,
                    args.flow_screen.screen.fixed,
                ):
                    try:
                        res = extract_schema_default_value(
                            schema=screen.raw_schema,
                            fixed=args.flow_screen.screen.fixed,
                            path=enum_path,
                        )
                    except KeyError as e:
                        return Response(
                            status_code=409,
                            content=StandardErrorResponse[ERROR_409_TYPES](
                                type="screen_input_parameters_wont_match",
                                message=f"enum discriminator at {pretty_path(enum_path)} for screen {screen.slug} could not be determined: {e}",
                            ).model_dump_json(),
                            headers={"Content-Type": "application/json; charset=utf-8"},
                        )

                    if res.type == "success" and res.value not in allowed_values:
                        return Response(
                            status_code=409,
                            content=StandardErrorResponse[ERROR_409_TYPES](
                                type="screen_input_parameters_wont_match",
                                message=f"enum discriminator at {pretty_path(enum_path)} for screen {screen.slug} didn't match allowed values: {allowed_values}",
                            ).model_dump_json(),
                            headers={"Content-Type": "application/json; charset=utf-8"},
                        )

                    if res.type == "success":
                        discriminators[tuple(enum_path[:-1])] = allowed_values.index(
                            res.value
                        )
                    else:
                        discriminators[tuple(enum_path[:-1])] = 0

        except UserSafeError as e:
            return e.response

        for path, value in iter_flattened_object(args.flow_screen.screen.fixed):
            output_schema = _get_output_schema(screen, path, -1, discriminators)
            if output_schema.type == "failure":
                return output_schema.error_response

            err = best_match(OAS30Validator(output_schema.schema).iter_errors(value))
            if err is not None:
                return Response(
                    status_code=409,
                    content=StandardErrorResponse[ERROR_409_TYPES](
                        type="screen_input_parameters_wont_match",
                        message=f"fixed parameter {pretty_path(path)} for screen {screen.slug} didn't match schema: {err}",
                    ).model_dump_json(),
                    headers={"Content-Type": "application/json; charset=utf-8"},
                )

            if output_schema.schema.get("type") == "string":
                output_fmt = output_schema.schema.get("format")
                if output_fmt == "image_uid":
                    conn = await itgs.conn()
                    cursor = conn.cursor()
                    response = await cursor.execute(
                        "SELECT 1 FROM image_files WHERE uid=?", (value,)
                    )
                    if not response.results:
                        return Response(
                            status_code=409,
                            content=StandardErrorResponse[ERROR_409_TYPES](
                                type="screen_input_parameters_wont_match",
                                message=f"fixed parameter {pretty_path(path)} for screen {screen.slug} is a string with format image_uid, but no image with that uid exists",
                            ).model_dump_json(),
                            headers={"Content-Type": "application/json; charset=utf-8"},
                        )
                elif output_fmt == "content_uid":
                    conn = await itgs.conn()
                    cursor = conn.cursor()
                    response = await cursor.execute(
                        "SELECT 1 FROM content_files WHERE uid=?", (value,)
                    )
                    if not response.results:
                        return Response(
                            status_code=409,
                            content=StandardErrorResponse[ERROR_409_TYPES](
                                type="screen_input_parameters_wont_match",
                                message=f"fixed parameter {pretty_path(path)} for screen {screen.slug} is a string with format content_uid, but no content with that uid exists",
                            ).model_dump_json(),
                            headers={"Content-Type": "application/json; charset=utf-8"},
                        )
                elif output_fmt == "journey_uid":
                    conn = await itgs.conn()
                    cursor = conn.cursor()
                    response = await cursor.execute(
                        "SELECT 1 FROM journeys WHERE uid=?", (value,)
                    )
                    if not response.results:
                        return Response(
                            status_code=409,
                            content=StandardErrorResponse[ERROR_409_TYPES](
                                type="screen_input_parameters_wont_match",
                                message=f"fixed parameter {pretty_path(path)} for screen {screen.slug} is a string with format journey_uid, but no journey with that uid exists",
                            ).model_dump_json(),
                            headers={"Content-Type": "application/json; charset=utf-8"},
                        )
                elif output_fmt == "course_uid":
                    conn = await itgs.conn()
                    cursor = conn.cursor()
                    response = await cursor.execute(
                        "SELECT 1 FROM courses WHERE uid=?", (value,)
                    )
                    if not response.results:
                        return Response(
                            status_code=409,
                            content=StandardErrorResponse[ERROR_409_TYPES](
                                type="screen_input_parameters_wont_match",
                                message=f"fixed parameter {pretty_path(path)} for screen {screen.slug} is a string with format course_uid, but no course with that uid exists",
                            ).model_dump_json(),
                            headers={"Content-Type": "application/json; charset=utf-8"},
                        )
                elif output_fmt == "interactive_prompt_uid":
                    conn = await itgs.conn()
                    cursor = conn.cursor()
                    response = await cursor.execute(
                        "SELECT 1 FROM interactive_prompts WHERE uid=?", (value,)
                    )
                    if not response.results:
                        return Response(
                            status_code=409,
                            content=StandardErrorResponse[ERROR_409_TYPES](
                                type="screen_input_parameters_wont_match",
                                message=f"fixed parameter {pretty_path(path)} for screen {screen.slug} is a string with format interactive_prompt_uid, but no interactive prompt with that uid exists",
                            ).model_dump_json(),
                            headers={"Content-Type": "application/json; charset=utf-8"},
                        )
                elif output_fmt == "flow_slug":
                    if value is None:
                        continue  # must be nullable or we would have gotten a standard error

                    flow = await get_client_flow(itgs, slug=value)
                    if flow is None:
                        return Response(
                            status_code=409,
                            content=StandardErrorResponse[ERROR_409_TYPES](
                                type="screen_input_parameters_wont_match",
                                message=f"fixed parameter {pretty_path(path)} for screen {screen.slug} is a string with format flow_slug, but no flow with that slug ({value}) exists",
                            ).model_dump_json(),
                            headers={"Content-Type": "application/json; charset=utf-8"},
                        )

                    if value not in args.flow_screen.allowed_triggers:
                        return Response(
                            status_code=409,
                            content=StandardErrorResponse[ERROR_409_TYPES](
                                type="screen_input_parameters_wont_match",
                                message=f"fixed parameter {pretty_path(path)} for screen {screen.slug} is a string with format flow_slug, but that flow ({value}) is not allowed to be triggered from this screen",
                            ).model_dump_json(),
                            headers={"Content-Type": "application/json; charset=utf-8"},
                        )
                elif output_fmt == "journal_entry_uid":
                    if value is None:
                        continue

                    conn = await itgs.conn()
                    cursor = conn.cursor()
                    response = await cursor.execute(
                        "SELECT 1 FROM journal_entries, users WHERE journal_entries.uid=? AND users.sub=? AND users.id=journal_entries.user_id",
                        (value, auth_result.result.sub),
                    )
                    if not response.results:
                        return Response(
                            status_code=409,
                            content=StandardErrorResponse[ERROR_409_TYPES](
                                type="screen_input_parameters_wont_match",
                                message=f"fixed parameter {pretty_path(path)} for screen {screen.slug} is a string with format journal_entry_uid, but no journal entry with that uid exists for the current user",
                            ).model_dump_json(),
                            headers={"Content-Type": "application/json; charset=utf-8"},
                        )

        for req_param in iter_flow_screen_required_parameters(args.flow_screen):
            input_schema = _get_input_schema(
                args.flow.client_schema,
                args.flow.server_schema,
                req_param.input_path,
                req_param.idx,
                allow_auto_extract=req_param.usage_type == "string_formattable",
                allow_missing=(
                    req_param.variable_parameter.type == "extract"
                    and req_param.variable_parameter.skip_if_missing
                    or req_param.usage_type == "string_formattable"
                ),
            )
            if input_schema.type == "failure":
                return input_schema.error_response

            output_schema = _get_output_schema(
                screen, req_param.output_path, req_param.idx, discriminators
            )
            if output_schema.type == "failure":
                return output_schema.error_response

            match_result = _determine_if_appropriate(
                input_schema, output_schema, req_param
            )
            if match_result.type == "failure":
                return match_result.error_response

            try:
                deep_extract(args.flow_screen.screen.fixed, req_param.output_path)
                return Response(
                    status_code=409,
                    content=StandardErrorResponse[ERROR_409_TYPES](
                        type="screen_input_parameters_redundant",
                        message=f"variable[{req_param.idx}] overwrites fixed value at {pretty_path(req_param.output_path)}: remove one, as these are redundant",
                    ).model_dump_json(),
                    headers={"Content-Type": "application/json; charset=utf-8"},
                )
            except KeyError:
                pass

        for (
            enum_path_with_special_indices,
            allowed_values,
        ) in screen.realizer.iter_enum_discriminators():
            for enum_path in fix_special_enum_path_indices(
                enum_path_with_special_indices,
                screen.raw_schema,
                args.flow_screen.screen.fixed,
            ):
                try:
                    value = deep_extract(args.flow_screen.screen.fixed, enum_path)
                except KeyError:
                    # Not specifying is ok; if it is required, we'll catch it when we go to
                    # check the example. However, they can't specify it via a variable
                    # because that makes the admin area way too complex

                    for variable_input in args.flow_screen.screen.variable:
                        if variable_input.output_path == enum_path:
                            return Response(
                                status_code=409,
                                content=StandardErrorResponse[ERROR_409_TYPES](
                                    type="screen_input_parameters_wont_match",
                                    message=f"enum discriminator at {pretty_path(enum_path)} for screen {screen.slug} must be fixed, not variable",
                                ).model_dump_json(),
                                headers={
                                    "Content-Type": "application/json; charset=utf-8"
                                },
                            )
                    continue

                if value not in allowed_values:
                    return Response(
                        status_code=409,
                        content=StandardErrorResponse[ERROR_409_TYPES](
                            type="screen_input_parameters_wont_match",
                            message=f"enum discriminator at {pretty_path(enum_path)} for screen {screen.slug} didn't match allowed values: {allowed_values}",
                        ).model_dump_json(),
                        headers={"Content-Type": "application/json; charset=utf-8"},
                    )

        # TODO -> loop through the screens schema itself to make sure it will
        # receive all required parameters from either fixed or variable.

        requested_standard_parameters = set()
        for path in get_requested_standard_parameters(args.flow_screen.screen):
            requested_standard_parameters.add(tuple(path))

        standard_parameters = await create_standard_parameters(
            itgs,
            user_sub=auth_result.result.sub,
            requested=requested_standard_parameters,
            now=time.time(),
            platform="browser",
        )

        test_flow = ClientFlow(
            uid="oseh_cf_test",
            slug="__test__",
            client_schema=client_schema_validator,
            client_schema_raw=args.flow.client_schema,
            server_schema=server_schema_validator,
            server_schema_raw=args.flow.server_schema,
            replaces=False,
            screens=[args.flow_screen],
            rules=[],
            flags=ClientFlowFlag.ANDROID_TRIGGERABLE
            | ClientFlowFlag.IOS_TRIGGERABLE
            | ClientFlowFlag.BROWSER_TRIGGERABLE,
        )

        server_transformation = await handle_trigger_time_server_transformations(
            itgs,
            flow=test_flow,
            flow_screen=args.flow_screen,
            flow_server_parameters=args.server_parameters,
        )

        if server_transformation.type == "skip":
            return Response(
                status_code=409,
                content=StandardErrorResponse[ERROR_409_TYPES](
                    type="skip",
                    message="screen would be skipped at trigger time; test with different parameters",
                ).model_dump_json(),
            )

        client_transformation = await handle_trigger_time_client_transformations(
            itgs,
            flow=test_flow,
            flow_screen=server_transformation.transformed_flow_screen,
            flow_client_parameters=args.client_parameters,
        )

        final_flow_screen = client_transformation.transformed_flow_screen

        screen_input_parameters = produce_screen_input_parameters(
            flow_screen=final_flow_screen,
            transformed_flow_client_parameters=client_transformation.transformed_client_parameters,
            transformed_flow_server_parameters=server_transformation.transformed_server_parameters,
            standard_parameters=standard_parameters,
        )

        err = best_match(screen.schema.iter_errors(screen_input_parameters))
        if err is not None:
            # known things that might get to here:
            # - missing required parameters for the screen (since we didn't check for that)
            return Response(
                status_code=409,
                content=StandardErrorResponse[ERROR_409_TYPES](
                    type="screen_input_parameters_didnt_match",
                    message=str(err),
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        # get an error here instead of later, in case there is one
        await screen.realizer.convert_validated_to_realized(
            itgs,
            for_user_sub=auth_result.result.sub,
            input=screen_input_parameters,
        )

        if args.dry_run:
            return Response(status_code=202)

        conn = await itgs.conn()
        cursor = conn.cursor()

        response = await cursor.execute(
            """
INSERT INTO user_client_screens (
    uid,
    user_id,
    outer_counter,
    inner_counter,
    client_flow_id,
    client_screen_id,
    flow_client_parameters,
    flow_server_parameters,
    screen,
    added_at
)
SELECT
    ?, 
    users.id, 
    COALESCE(
        (
            SELECT ucs.outer_counter
            FROM user_client_screens AS ucs
            WHERE ucs.user_id = users.id
            ORDER BY ucs.outer_counter DESC
            LIMIT 1
        ),
        0
    ) + 1,
    1,
    NULL,
    client_screens.id,
    ?,
    ?,
    ?,
    ?
FROM users, client_screens
WHERE
    users.sub = ?
    AND client_screens.slug = ?
    AND client_screens.schema = ?
            """,
            (
                f"oseh_ucs_{secrets.token_urlsafe(16)}",
                json.dumps(client_transformation.transformed_client_parameters, sort_keys=True),
                json.dumps(server_transformation.transformed_server_parameters, sort_keys=True),
                json.dumps(
                    final_flow_screen.model_dump(), sort_keys=True
                ),
                time.time(),
                auth_result.result.sub,
                screen.slug,
                json.dumps(screen.raw_schema, sort_keys=True),
            ),
        )
        assert response.rows_affected == 1, response
        return Response(status_code=202)


@dataclass
class FindSchemaSuccess:
    type: Literal["success"]
    safe: bool
    """For an input schema, this is True if it is trusted and false if it is untrusted. For
    an output schema, this is True if any input is acceptable and False if the input must
    be trusted.
    """
    schema: dict


@dataclass
class FindSchemaNotFound:
    type: Literal["failure"]
    error_response: Response


FindSchemaResult = Union[FindSchemaSuccess, FindSchemaNotFound]


def _get_input_schema(
    client_schema: dict,
    server_schema: dict,
    input_path: List[str],
    variable_parameter_idx: int,
    allow_auto_extract: bool,
    allow_missing: bool,
) -> FindSchemaResult:
    """Determines what type of variable is returned at the given path, as an
    openapi 3.0.3 schema object with an example. Assumes we've already
    verified the client and server schema.

    Args:
        client_schema (dict): The client schema for the flow.
        server_schema (dict): The server schema for the flow.
        input_path (List[str]): The path to the variable in the schema.
        variable_parameter_idx (int): The index of the variable parameter in the flow screen,
            for error formatting
        allow_auto_extract (bool): If automatic extraction is allowed for this variable,
            i.e., converting course_uid to the corresponding course as an object. Typically,
            this is only true for string format (for convenience)
        allow_missing (bool): If true, we will not verify that the input_path will be extractable
            from the target, only that if it can be extracted it will match the returned schema.
            For example, for {"foo": {"bar": null}}, $.foo.bar is extractable but null, however
            for {} $.foo.bar is not extractable. Note that this assumes that the caller fills in
            default values where applicable.
    """
    if not input_path:
        return FindSchemaNotFound(
            type="failure",
            error_response=Response(
                status_code=409,
                content=StandardErrorResponse[ERROR_409_TYPES](
                    type="screen_input_parameters_wont_match",
                    message=f"variable[{variable_parameter_idx}] references blank input",
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
            ),
        )

    src = input_path[0]
    if src == "standard":
        std = get_standard_parameter_schema(input_path[1:])
        if std is None:
            return FindSchemaNotFound(
                type="failure",
                error_response=Response(
                    status_code=409,
                    content=StandardErrorResponse[ERROR_409_TYPES](
                        type="screen_input_parameters_wont_match",
                        message=f"variable[{variable_parameter_idx}] references {pretty_path(input_path)}, but {input_path[1:]} is not a supported standard parameter",
                    ).model_dump_json(),
                    headers={"Content-Type": "application/json; charset=utf-8"},
                ),
            )
        return FindSchemaSuccess(
            type="success",
            safe=False,
            schema=std,
        )

    if src == "client":
        top_schema = client_schema
        safe = False
    elif src == "server":
        top_schema = server_schema
        safe = True
    else:
        return FindSchemaNotFound(
            type="failure",
            error_response=Response(
                status_code=409,
                content=StandardErrorResponse[ERROR_409_TYPES](
                    type="screen_input_parameters_wont_match",
                    message=f"variable[{variable_parameter_idx}] references {pretty_path(input_path)}, which is unsupported (should start with standard, client, or server)",
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
            ),
        )

    made_it_to = input_path[:1]
    remaining = input_path[1:]
    current = top_schema
    schema_path: List[Union[str, int]] = [input_path[0]]
    defs = None
    while remaining:
        if defs is not None:
            # we're in a standard json schema, not our custom format anymore
            ref = current.get("$ref")
            if ref is not None:
                prefix = "#/$defs/"
                assert isinstance(ref, str) and ref.startswith(
                    prefix
                ), f"variable[{variable_parameter_idx}] references {pretty_path(input_path)}, which is a bad reference at {pretty_path(schema_path)} ({ref})"
                ref_key = ref[len(prefix) :]
                assert (
                    ref_key in defs
                ), f"variable[{variable_parameter_idx}] references {pretty_path(input_path)}, which is a bad reference at {pretty_path(schema_path)} ({ref_key} not found in defs, using {ref})"
                current = defs[ref_key]
                schema_path.append(ref)
                continue

            # allOf is sometimes used to switch to a ref (pydantic likes to do this)
            all_of = current.get("allOf")
            if all_of is not None:
                assert isinstance(
                    all_of, list
                ), f"variable[{variable_parameter_idx}] references {pretty_path(input_path)}, which is a bad allOf at {pretty_path(schema_path)}"
                assert (
                    len(all_of) == 1
                ), f"variable[{variable_parameter_idx}] references {pretty_path(input_path)}, which is a bad allOf at {pretty_path(schema_path)} (should have exactly one element)"
                current = all_of[0]
                schema_path.extend(["allOf", 0])
                continue

            # anyOf is used instead of nullable
            any_of = current.get("anyOf")
            if any_of is not None:
                assert isinstance(
                    any_of, list
                ), f"variable[{variable_parameter_idx}] references {pretty_path(input_path)}, which is a bad anyOf at {pretty_path(schema_path)}"
                assert all(
                    isinstance(x, dict) for x in any_of
                ), f"variable[{variable_parameter_idx}] references {pretty_path(input_path)}, which is a bad anyOf at {pretty_path(schema_path)}"
                non_null_any_of = [
                    (idx, x) for idx, x in enumerate(any_of) if x.get("type") != "null"
                ]
                assert (
                    len(non_null_any_of) == 1
                ), f"variable[{variable_parameter_idx}] references {pretty_path(input_path)}, which is a bad anyOf at {pretty_path(schema_path)} (should have exactly one non-null element)"

                if len(remaining) > 1 and len(non_null_any_of) < len(any_of):
                    return FindSchemaNotFound(
                        type="failure",
                        error_response=Response(
                            status_code=409,
                            content=StandardErrorResponse[ERROR_409_TYPES](
                                type="screen_input_parameters_wont_match",
                                message=f"variable[{variable_parameter_idx}] references {pretty_path(input_path)}, which is nullable at {pretty_path(made_it_to)} (schema path {pretty_path(schema_path)})",
                            ).model_dump_json(),
                            headers={"Content-Type": "application/json; charset=utf-8"},
                        ),
                    )

                current = non_null_any_of[0][1]
                schema_path.extend(["anyOf", non_null_any_of[0][0]])
                continue

        nullable = current.get("nullable", False)
        if nullable is not False and not allow_missing:
            if len(remaining) > 1:
                return FindSchemaNotFound(
                    type="failure",
                    error_response=Response(
                        status_code=409,
                        content=StandardErrorResponse[ERROR_409_TYPES](
                            type="screen_input_parameters_wont_match",
                            message=f"variable[{variable_parameter_idx}] references {pretty_path(input_path)}, which is nullable at {pretty_path(made_it_to)} (schema path {pretty_path(schema_path)})",
                        ).model_dump_json(),
                        headers={"Content-Type": "application/json; charset=utf-8"},
                    ),
                )

        current_type = current.get("type")
        if current_type == "string":
            current_format = current.get("format")
            if current_format == "course_uid":
                if not safe or not allow_auto_extract:
                    return FindSchemaNotFound(
                        type="failure",
                        error_response=Response(
                            status_code=409,
                            content=StandardErrorResponse[ERROR_409_TYPES](
                                type="screen_input_parameters_wont_match",
                                message=f"variable[{variable_parameter_idx}] references {pretty_path(input_path)}, which references ExternalCourse at {pretty_path(made_it_to)} (schema path {pretty_path(schema_path)}), but is not automatically extracted",
                            ).model_dump_json(),
                            headers={"Content-Type": "application/json; charset=utf-8"},
                        ),
                    )

                current = ExternalCourse.model_json_schema()
                defs = current.get("$defs", dict())
                schema_path.append("#ExternalCourse")
                continue
            elif current_format == "journey_uid":
                if not safe or not allow_auto_extract:
                    return FindSchemaNotFound(
                        type="failure",
                        error_response=Response(
                            status_code=409,
                            content=StandardErrorResponse[ERROR_409_TYPES](
                                type="screen_input_parameters_wont_match",
                                message=f"variable[{variable_parameter_idx}] references {pretty_path(input_path)}, which references ExternalJourney at {pretty_path(made_it_to)} (schema path {pretty_path(schema_path)}), but is not automatically extracted",
                            ).model_dump_json(),
                            headers={"Content-Type": "application/json; charset=utf-8"},
                        ),
                    )

                current = ExternalJourney.model_json_schema()
                defs = current.get("$defs", dict())
                schema_path.append("#ExternalJourney")
                continue

        if current_type == "object":
            required = current.get("required", [])

            assert isinstance(required, list)

            properties = current.get("properties", dict())
            assert isinstance(properties, dict)

            nxt_key = remaining[0]
            nxt = properties.get(nxt_key)
            if nxt is None:
                return FindSchemaNotFound(
                    type="failure",
                    error_response=Response(
                        status_code=409,
                        content=StandardErrorResponse[ERROR_409_TYPES](
                            type="screen_input_parameters_wont_match",
                            message=f"variable[{variable_parameter_idx}] references {pretty_path(input_path)}, which is not in properties at {pretty_path(made_it_to)} (schema path {pretty_path(schema_path)})",
                        ).model_dump_json(),
                        headers={"Content-Type": "application/json; charset=utf-8"},
                    ),
                )

            if (
                remaining[0] not in required
                and not allow_missing
                and "default" not in nxt
            ):
                return FindSchemaNotFound(
                    type="failure",
                    error_response=Response(
                        status_code=409,
                        content=StandardErrorResponse[ERROR_409_TYPES](
                            type="screen_input_parameters_wont_match",
                            message=f"variable[{variable_parameter_idx}] references {pretty_path(input_path)}, which is not required at {pretty_path(made_it_to)} (schema path {pretty_path(schema_path)}) and has no default value. Either require it or provide a default value.",
                        ).model_dump_json(),
                        headers={"Content-Type": "application/json; charset=utf-8"},
                    ),
                )

            current = nxt
            made_it_to.append(remaining.pop(0))
            schema_path.extend(["properties", nxt_key])
            continue

        if current_type == "array":
            nxt_key = remaining[0]
            try:
                key_as_int = int(nxt_key)
            except ValueError:
                return FindSchemaNotFound(
                    type="failure",
                    error_response=Response(
                        status_code=409,
                        content=StandardErrorResponse[ERROR_409_TYPES](
                            type="screen_input_parameters_wont_match",
                            message=f"variable[{variable_parameter_idx}] references {pretty_path(input_path)}, which is an array at {pretty_path(made_it_to)} (schema path {pretty_path(schema_path)}), but {nxt_key} is not an integer",
                        ).model_dump_json(),
                        headers={"Content-Type": "application/json; charset=utf-8"},
                    ),
                )

            items = current.get("items")
            if items is None:
                return FindSchemaNotFound(
                    type="failure",
                    error_response=Response(
                        status_code=409,
                        content=StandardErrorResponse[ERROR_409_TYPES](
                            type="screen_input_parameters_wont_match",
                            message=f"variable[{variable_parameter_idx}] references {pretty_path(input_path)}, which is an array at {pretty_path(made_it_to)} (schema path {pretty_path(schema_path)}), but without an items schema",
                        ).model_dump_json(),
                        headers={"Content-Type": "application/json; charset=utf-8"},
                    ),
                )

            min_items = current.get("minItems", 0)
            if min_items <= key_as_int:
                return FindSchemaNotFound(
                    type="failure",
                    error_response=Response(
                        status_code=409,
                        content=StandardErrorResponse[ERROR_409_TYPES](
                            type="screen_input_parameters_wont_match",
                            message=(
                                f"variable[{variable_parameter_idx}] references {pretty_path(input_path)}, "
                                f"which is an array at {pretty_path(made_it_to)} (schema path {pretty_path(schema_path)}), "
                                f"but with too few items (requires {min_items}, "
                                f"but needs to require at least {key_as_int + 1})"
                            ),
                        ).model_dump_json(),
                        headers={"Content-Type": "application/json; charset=utf-8"},
                    ),
                )

            current = items
            made_it_to.append(remaining.pop(0))
            schema_path.append("items")
            continue

        return FindSchemaNotFound(
            type="failure",
            error_response=Response(
                status_code=409,
                content=StandardErrorResponse[ERROR_409_TYPES](
                    type="screen_input_parameters_wont_match",
                    message=f"variable[{variable_parameter_idx}] references {pretty_path(input_path)}, "
                    f"which is not an object or array (is a {current_type}) at {pretty_path(made_it_to)} ("
                    f"schema path: {pretty_path(schema_path)})",
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
            ),
        )

    return FindSchemaSuccess(
        type="success",
        safe=safe,
        schema=current,
    )


def _get_output_schema(
    screen: ClientScreen,
    path: Union[List[Union[int, str]], List[int], List[str]],
    variable_parameter_idx: int,
    discriminators: Dict[tuple, int],
) -> FindSchemaResult:
    """Determines what variable is required for the given screen
    at the given path, if any

    Args:
        screen (ClientFlowScreen): The screen to check
        path (List[str]): The path to the variable in the screens schema to fetch
        variable_parameter_idx (int): The index of the variable parameter in the flow screen,
            for error formatting, or -1 for fixed
        discriminators (dict[tuple[str, ...], int]): for each path in the screen schema which
            is an x-enum-discriminator oneOf object, the index of the oneOf object that should
            be used.
    """
    current = screen.raw_schema
    made_it_to: List[Union[str, int]] = []
    remaining = path.copy()

    def error_source():
        if variable_parameter_idx == -1:
            return "fixed"
        return f"variable[{variable_parameter_idx}]"

    while remaining:
        current_type = current.get("type")
        if current_type == "object":
            if "x-enum-discriminator" in current:
                discriminator_key = tuple(made_it_to)
                discriminated_to_index = discriminators.get(discriminator_key)
                if discriminated_to_index is None:
                    return FindSchemaNotFound(
                        type="failure",
                        error_response=Response(
                            status_code=409,
                            content=StandardErrorResponse[ERROR_409_TYPES](
                                type="screen_input_parameters_wont_match",
                                message=f"{error_source()} targets {pretty_path(path)}, which is an enum discriminator at {pretty_path(made_it_to)}, but was not discriminated in fixed\n\n{discriminator_key=}\n{discriminators=}",
                            ).model_dump_json(),
                            headers={"Content-Type": "application/json; charset=utf-8"},
                        ),
                    )

                oneof = current.get("oneOf")
                assert isinstance(
                    oneof, list
                ), f"discriminator without oneof at {pretty_path(made_it_to)}"
                assert (
                    0 <= discriminated_to_index < len(oneof)
                ), f"discriminator out of range at {pretty_path(made_it_to)}"
                current = oneof[discriminated_to_index]
                continue

            properties = current.get("properties", None)
            if properties is None:
                return FindSchemaSuccess(type="success", safe=False, schema={})
            assert isinstance(properties, dict)

            nxt = properties.get(remaining[0])
            if nxt is None:
                return FindSchemaNotFound(
                    type="failure",
                    error_response=Response(
                        status_code=409,
                        content=StandardErrorResponse[ERROR_409_TYPES](
                            type="screen_input_parameters_wont_match",
                            message=f"{error_source()} targets {pretty_path(path)}, which is not in properties at {pretty_path(made_it_to)}",
                        ).model_dump_json(),
                        headers={"Content-Type": "application/json; charset=utf-8"},
                    ),
                )

            current = nxt
            made_it_to.append(remaining.pop(0))
            continue
        elif current_type == "array":
            items = current.get("items")
            if items is None:
                return FindSchemaNotFound(
                    type="failure",
                    error_response=Response(
                        status_code=409,
                        content=StandardErrorResponse[ERROR_409_TYPES](
                            type="screen_input_parameters_wont_match",
                            message=f"{error_source()} targets {pretty_path(path)}, which is an array at {pretty_path(made_it_to)}, but without an items schema",
                        ).model_dump_json(),
                        headers={"Content-Type": "application/json; charset=utf-8"},
                    ),
                )

            part = remaining.pop(0)
            if not isinstance(part, int):
                return FindSchemaNotFound(
                    type="failure",
                    error_response=Response(
                        status_code=409,
                        content=StandardErrorResponse[ERROR_409_TYPES](
                            type="screen_input_parameters_wont_match",
                            message=f"{error_source()} targets {pretty_path(path)}, which is an array at {pretty_path(made_it_to)}, but the path part {part} is not an integer",
                        ).model_dump_json(),
                        headers={"Content-Type": "application/json; charset=utf-8"},
                    ),
                )

            current = items
            made_it_to.append(part)
            continue

        return FindSchemaNotFound(
            type="failure",
            error_response=Response(
                status_code=409,
                content=StandardErrorResponse[ERROR_409_TYPES](
                    type="screen_input_parameters_wont_match",
                    message=f"{error_source()} targets {pretty_path(path)}, which is a(n) {current_type} at {pretty_path(made_it_to)} (unsupported target for indexing)",
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
            ),
        )

    safe = True
    to_check = [(current, made_it_to)]
    while to_check:
        schema, path = to_check.pop()

        schema_type = schema.get("type")
        if schema_type == "object":
            properties = schema.get("properties", dict())
            assert isinstance(properties, dict)
            for key, value in properties.items():
                to_check.append((value, path + [key]))
            continue

        if schema_type == "array":
            items = schema.get("items")
            assert isinstance(items, dict)
            to_check.append((items, path + ["items"]))
            continue

        schema_format = schema.get("format")
        if (schema_type, schema_format) in UNSAFE_SCREEN_SCHEMA_TYPES:
            safe = False
            break

    return FindSchemaSuccess(type="success", safe=safe, schema=current)


@dataclass
class IsAppropriateSuccess:
    type: Literal["success"]


@dataclass
class IsAppropriateFailure:
    type: Literal["failure"]
    error_response: Response


def _determine_if_appropriate(
    input_schema: FindSchemaSuccess,
    output_schema: FindSchemaSuccess,
    req_param: FlowScreenRequiredParameter,
):
    """Determines if its appropriate to take an object described by the input_schema
    and put it into the output_schema.

    Args:
        input_schema (FindSchemaSuccess): The schema of the input
        output_schema (FindSchemaSuccess): The schema of the output
        req_param (FlowScreenRequiredParameter): The required parameter to check
    """
    if not input_schema.safe and not output_schema.safe:
        return IsAppropriateFailure(
            type="failure",
            error_response=Response(
                status_code=409,
                content=StandardErrorResponse[ERROR_409_TYPES](
                    type="screen_is_unsafe",
                    message=f"variable[{req_param.idx}] uses an unsafe input, but the target requires a safe input",
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
            ),
        )

    if req_param.usage_type == "string_formattable":
        output_type = output_schema.schema.get("type")
        if output_type != "string":
            return IsAppropriateFailure(
                type="failure",
                error_response=Response(
                    status_code=409,
                    content=StandardErrorResponse[ERROR_409_TYPES](
                        type="screen_input_parameters_wont_match",
                        message=f"variable[{req_param.idx}] produces a string, but the target is a {output_type}",
                    ).model_dump_json(),
                    headers={"Content-Type": "application/json; charset=utf-8"},
                ),
            )
        return IsAppropriateSuccess(type="success")

    if req_param.usage_type == "copy":
        if (
            input_schema.schema.get("nullable", False) is True
            and output_schema.schema.get("nullable", False) is not True
        ):
            return IsAppropriateFailure(
                type="failure",
                error_response=Response(
                    status_code=409,
                    content=StandardErrorResponse[ERROR_409_TYPES](
                        type="screen_input_parameters_wont_match",
                        message=f"variable[{req_param.idx}] copies to target, but the input is nullable and the target is not",
                    ).model_dump_json(),
                    headers={"Content-Type": "application/json; charset=utf-8"},
                ),
            )

        input_example = input_schema.schema.get("example")
        err = best_match(
            OAS30Validator(output_schema.schema).iter_errors(input_example)
        )
        if err is not None:
            return IsAppropriateFailure(
                type="failure",
                error_response=Response(
                    status_code=409,
                    content=StandardErrorResponse[ERROR_409_TYPES](
                        type="screen_input_parameters_wont_match",
                        message=f"variable[{req_param.idx}] copies to target, but the example of the input doesnt match the output schema: {err}",
                    ).model_dump_json(),
                    headers={"Content-Type": "application/json; charset=utf-8"},
                ),
            )

        return IsAppropriateSuccess(type="success")

    if req_param.usage_type == "extract":
        if not input_schema.safe:
            return IsAppropriateFailure(
                type="failure",
                error_response=Response(
                    status_code=409,
                    content=StandardErrorResponse[ERROR_409_TYPES](
                        type="screen_is_unsafe",
                        message=f"variable[{req_param.idx}] extracts from an unsafe input {pretty_path(req_param.input_path)}",
                    ).model_dump_json(),
                    headers={"Content-Type": "application/json; charset=utf-8"},
                ),
            )

        if input_schema.schema.get("type") != "string":
            return IsAppropriateFailure(
                type="failure",
                error_response=Response(
                    status_code=409,
                    content=StandardErrorResponse[ERROR_409_TYPES](
                        type="screen_input_parameters_wont_match",
                        message=f"variable[{req_param.idx}] extracts from non-extractable input {pretty_path(req_param.input_path)}",
                    ).model_dump_json(),
                    headers={"Content-Type": "application/json; charset=utf-8"},
                ),
            )

        input_format = input_schema.schema.get("format")
        if input_format == "course_uid":
            extracting_schema = ExternalCourse.model_json_schema()
        elif input_format == "journey_uid":
            extracting_schema = ExternalJourney.model_json_schema()
        else:
            return IsAppropriateFailure(
                type="failure",
                error_response=Response(
                    status_code=409,
                    content=StandardErrorResponse[ERROR_409_TYPES](
                        type="screen_input_parameters_wont_match",
                        message=f"variable[{req_param.idx}] extracts from non-extractable input {pretty_path(req_param.input_path)}",
                    ).model_dump_json(),
                    headers={"Content-Type": "application/json; charset=utf-8"},
                ),
            )

        var_param = req_param.variable_parameter
        assert var_param.type == "extract"
        extract_target = extract_from_model_json_schema(
            extracting_schema, var_param.extracted_path
        )
        if extract_target.type != "success":
            return IsAppropriateFailure(
                type="failure",
                error_response=Response(
                    status_code=409,
                    content=StandardErrorResponse[ERROR_409_TYPES](
                        type="screen_input_parameters_wont_match",
                        message=f"variable[{req_param.idx}] extracts from {pretty_path(req_param.input_path)}, but the extraction path {pretty_path(var_param.extracted_path)} is not valid:\n\n${extract_target.failure_reason}\n@{extract_target.failed_path}",
                    ).model_dump_json(),
                    headers={"Content-Type": "application/json; charset=utf-8"},
                ),
            )

        # we don't usually get examples, so this is the best we can check
        if extract_target.schema.get("type") != output_schema.schema.get("type"):
            return IsAppropriateFailure(
                type="failure",
                error_response=Response(
                    status_code=409,
                    content=StandardErrorResponse[ERROR_409_TYPES](
                        type="screen_input_parameters_wont_match",
                        message=f"variable[{req_param.idx}] extracts from {pretty_path(req_param.input_path)}, but the extraction path {pretty_path(var_param.extracted_path)} produces a {extract_target.schema.get('type')!r}, not a {output_schema.schema.get('type')!r}",
                    ).model_dump_json(),
                    headers={"Content-Type": "application/json; charset=utf-8"},
                ),
            )

        if (
            extract_target.is_potentially_missing_or_none
            and output_schema.schema.get("nullable", False) is not True
            and not var_param.skip_if_missing
        ):
            return IsAppropriateFailure(
                type="failure",
                error_response=Response(
                    status_code=409,
                    content=StandardErrorResponse[ERROR_409_TYPES](
                        type="screen_input_parameters_wont_match",
                        message=f"variable[{req_param.idx}] extracts from {pretty_path(req_param.input_path)}, but the extraction path {pretty_path(var_param.extracted_path)} is nullable and the target is not",
                    ).model_dump_json(),
                    headers={"Content-Type": "application/json; charset=utf-8"},
                ),
            )

        return IsAppropriateSuccess(type="success")

    raise ValueError(f"Unsupported usage type: {req_param.usage_type}")


@dataclass(frozen=True)
class _SpecialEnumPathStackItem:
    path_to_here: List[Union[str, int]]
    path_from_here: List[Union[str, SpecialIndex]]
    schema: dict
    value: Any
    is_really_none: bool


def fix_special_enum_path_indices(
    enum_path_with_special_indices: List[Union[str, SpecialIndex]],
    screen_schema: dict,
    fixed: dict,
):
    """Yields new enum paths where the special index "array index" is replaced with one path
    per actual index in fixed
    """
    stack: List[_SpecialEnumPathStackItem] = [
        _SpecialEnumPathStackItem(
            path_to_here=[],
            path_from_here=enum_path_with_special_indices,
            schema=screen_schema,
            value=fixed,
            is_really_none=False,
        )
    ]
    while stack:
        item = stack.pop()
        if item.value is None and not item.is_really_none:
            if item.schema.get("default") is not None:
                stack.append(
                    _SpecialEnumPathStackItem(
                        path_to_here=item.path_to_here,
                        path_from_here=item.path_from_here,
                        schema=item.schema,
                        value=item.schema["default"],
                        is_really_none=item.is_really_none,
                    )
                )
                continue
            if item.schema.get("nullable", False) is not True:
                raise UserSafeError(
                    message="Expected nullable or default",
                    response=Response(
                        status_code=409,
                        content=StandardErrorResponse[ERROR_409_TYPES](
                            type="screen_input_parameters_wont_match",
                            message=f"cannot determine enum discriminator for {enum_path_with_special_indices} since {pretty_path(item.path_to_here)} has None value, None default, and is not nullable",
                        ).model_dump_json(),
                        headers={"Content-Type": "application/json; charset=utf-8"},
                    ),
                )
            stack.append(
                _SpecialEnumPathStackItem(
                    path_to_here=item.path_to_here,
                    path_from_here=item.path_from_here,
                    schema=item.schema,
                    value=None,
                    is_really_none=True,
                )
            )
            continue

        if len(item.path_from_here) == 1:
            # the last part is the discriminator field, which will be an object
            # with no properties set as it uses oneOf instead
            last_part = item.path_from_here[0]
            if not isinstance(last_part, str):
                raise UserSafeError(
                    message="Expected string in enum path for discriminator",
                    response=Response(
                        status_code=409,
                        content=StandardErrorResponse[ERROR_409_TYPES](
                            type="screen_input_parameters_wont_match",
                            message=f"cannot determine enum discriminator for {enum_path_with_special_indices} - we expect the last part is always a string",
                        ).model_dump_json(),
                        headers={"Content-Type": "application/json; charset=utf-8"},
                    ),
                )
            yield item.path_to_here + [last_part]
            continue
        if not item.path_from_here:
            raise UserSafeError(
                message="Expected more in enum path",
                response=Response(
                    status_code=409,
                    content=StandardErrorResponse[ERROR_409_TYPES](
                        type="screen_input_parameters_wont_match",
                        message=f"cannot determine enum discriminator for {enum_path_with_special_indices} - we expect the last part is always a string, but got nothing instead",
                    ).model_dump_json(),
                    headers={"Content-Type": "application/json; charset=utf-8"},
                ),
            )

        part = item.path_from_here[0]

        schema_type = item.schema.get("type")

        if schema_type == "object":
            if not isinstance(part, str):
                raise UserSafeError(
                    message="Expected string in enum path for object",
                    response=Response(
                        status_code=409,
                        content=StandardErrorResponse[ERROR_409_TYPES](
                            type="screen_input_parameters_wont_match",
                            message=f"cannot determine enum discriminator for {enum_path_with_special_indices} since {pretty_path(item.path_to_here)} is an object",
                        ).model_dump_json(),
                        headers={"Content-Type": "application/json; charset=utf-8"},
                    ),
                )
            properties = item.schema.get("properties", {})
            if part not in properties:
                raise UserSafeError(
                    message="Property not found in enum path",
                    response=Response(
                        status_code=409,
                        content=StandardErrorResponse[ERROR_409_TYPES](
                            type="screen_input_parameters_wont_match",
                            message=f"cannot determine enum discriminator for {enum_path_with_special_indices} since {pretty_path(item.path_to_here)} is not expected to have a {part} according to schema {item.schema}",
                        ).model_dump_json(),
                        headers={"Content-Type": "application/json; charset=utf-8"},
                    ),
                )

            if item.is_really_none:
                stack.append(
                    _SpecialEnumPathStackItem(
                        path_to_here=item.path_to_here + [part],
                        path_from_here=item.path_from_here[1:],
                        schema=properties[part],
                        value=item.value,
                        is_really_none=True,
                    )
                )
                continue

            if isinstance(item.value, dict) and part not in item.value:
                # we swap to the default value if its not required
                required = item.schema.get("required", [])
                if part not in required:
                    part_schema = properties[part]
                    if "default" not in part_schema:
                        raise UserSafeError(
                            message="Property not found in fixed",
                            response=Response(
                                status_code=409,
                                content=StandardErrorResponse[ERROR_409_TYPES](
                                    type="screen_input_parameters_wont_match",
                                    message=f"cannot determine enum discriminator for {enum_path_with_special_indices} since {pretty_path(item.path_to_here)} is missing {part}, which isnt required but has no default set (schema is bad)",
                                ).model_dump_json(),
                                headers={
                                    "Content-Type": "application/json; charset=utf-8"
                                },
                            ),
                        )
                    stack.append(
                        _SpecialEnumPathStackItem(
                            path_to_here=item.path_to_here + [part],
                            path_from_here=item.path_from_here[1:],
                            schema=properties[part],
                            value=part_schema["default"],
                            is_really_none=item.is_really_none,
                        )
                    )
                    continue

                raise UserSafeError(
                    message="Property not found in fixed",
                    response=Response(
                        status_code=409,
                        content=StandardErrorResponse[ERROR_409_TYPES](
                            type="screen_input_parameters_wont_match",
                            message=f"cannot determine enum discriminator for {enum_path_with_special_indices} since {pretty_path(item.path_to_here)} does not have property {part} in fixed and is required in schmea {item.schema}",
                        ).model_dump_json(),
                        headers={"Content-Type": "application/json; charset=utf-8"},
                    ),
                )

            if item.value is not None and not isinstance(item.value, dict):
                raise UserSafeError(
                    message="Expected object in fixed",
                    response=Response(
                        status_code=409,
                        content=StandardErrorResponse[ERROR_409_TYPES](
                            type="screen_input_parameters_wont_match",
                            message=f"cannot determine enum discriminator for {enum_path_with_special_indices} since {pretty_path(item.path_to_here)} is an object, but the corresponding value in fixed is a {type(item.value).__name__}, not a dict",
                        ).model_dump_json(),
                        headers={"Content-Type": "application/json; charset=utf-8"},
                    ),
                )

            stack.append(
                _SpecialEnumPathStackItem(
                    path_to_here=item.path_to_here + [part],
                    path_from_here=item.path_from_here[1:],
                    schema=properties[part],
                    value=item.value[part],
                    is_really_none=item.is_really_none,
                )
            )
            continue

        if schema_type != "array":
            raise UserSafeError(
                message="Expected array or object in enum path",
                response=Response(
                    status_code=409,
                    content=StandardErrorResponse[ERROR_409_TYPES](
                        type="screen_input_parameters_wont_match",
                        message=f"cannot determine enum discriminator for {enum_path_with_special_indices} since {pretty_path(item.path_to_here)} is a {schema_type}",
                    ).model_dump_json(),
                    headers={"Content-Type": "application/json; charset=utf-8"},
                ),
            )

        if part is not SpecialIndex.ARRAY_INDEX:
            raise UserSafeError(
                message="Expected array index in enum path",
                response=Response(
                    status_code=409,
                    content=StandardErrorResponse[ERROR_409_TYPES](
                        type="screen_input_parameters_wont_match",
                        message=f"cannot determine enum discriminator for {enum_path_with_special_indices} since {pretty_path(item.path_to_here)} is an array, but the part is not an array index",
                    ).model_dump_json(),
                    headers={"Content-Type": "application/json; charset=utf-8"},
                ),
            )

        if item.is_really_none:
            # this path is a dead end
            continue

        if not isinstance(item.value, list):
            raise UserSafeError(
                message="Expected array in fixed",
                response=Response(
                    status_code=409,
                    content=StandardErrorResponse[ERROR_409_TYPES](
                        type="screen_input_parameters_wont_match",
                        message=f"cannot determine enum discriminator for {enum_path_with_special_indices} since {pretty_path(item.path_to_here)} is an array, but the corresponding value in fixed is a {type(item.value).__name__}, not a list",
                    ).model_dump_json(),
                    headers={"Content-Type": "application/json; charset=utf-8"},
                ),
            )

        items = item.schema.get("items")
        if not isinstance(items, dict):
            raise UserSafeError(
                message="Expected items schema in array",
                response=Response(
                    status_code=409,
                    content=StandardErrorResponse[ERROR_409_TYPES](
                        type="screen_input_parameters_wont_match",
                        message=f"cannot determine enum discriminator for {enum_path_with_special_indices} since {pretty_path(item.path_to_here)} is an array, but the items schema is not a dict",
                    ).model_dump_json(),
                    headers={"Content-Type": "application/json; charset=utf-8"},
                ),
            )

        for idx, value in enumerate(item.value):
            stack.append(
                _SpecialEnumPathStackItem(
                    path_to_here=item.path_to_here + [idx],
                    path_from_here=item.path_from_here[1:],
                    schema=items,
                    value=value,
                    is_really_none=item.is_really_none,
                )
            )


def iter_flattened_object(o: Any):
    stack = [(o, [])]

    while stack:
        current, path = stack.pop()
        if isinstance(current, dict):
            for key, value in current.items():
                stack.append((value, path + [key]))
        elif isinstance(current, list):
            for idx, value in enumerate(current):
                stack.append((value, path + [idx]))
        else:
            yield path, current
