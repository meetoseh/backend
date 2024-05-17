import json
import secrets
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Annotated, Any, Dict, List, Optional, Literal, Union
from lib.client_flows.client_flow_screen import ClientFlowScreen
from lib.client_flows.helper import (
    check_oas_30_schema,
    deep_extract,
    extract_schema_default_value,
    iter_flow_screen_required_parameters,
    pretty_path,
    produce_screen_input_parameters,
)
from lib.client_flows.screen_cache import ClientScreen, get_client_screen
from lib.client_flows.screen_schema import UNSAFE_SCREEN_SCHEMA_TYPES
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from itgs import Itgs
from auth import auth_admin
from openapi_schema_validator import OAS30Validator
from jsonschema.exceptions import best_match
from dataclasses import dataclass

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

        err = best_match(
            OAS30Validator(args.flow.client_schema).iter_errors(args.client_parameters)
        )
        if err is not None:
            return Response(
                status_code=409,
                content=StandardErrorResponse[ERROR_409_TYPES](
                    type="client_parameters_mismatch",
                    message=str(err),
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        err = best_match(
            OAS30Validator(args.flow.server_schema).iter_errors(args.server_parameters)
        )
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
        for enum_path, allowed_values in screen.realizer.iter_enum_discriminators():
            try:
                value = extract_schema_default_value(
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

            if value not in allowed_values:
                return Response(
                    status_code=409,
                    content=StandardErrorResponse[ERROR_409_TYPES](
                        type="screen_input_parameters_wont_match",
                        message=f"enum discriminator at {pretty_path(enum_path)} for screen {screen.slug} didn't match allowed values: {allowed_values}",
                    ).model_dump_json(),
                    headers={"Content-Type": "application/json; charset=utf-8"},
                )

            discriminators[tuple(enum_path[:-1])] = allowed_values.index(value)

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

        for (
            input_path,
            output_path,
            usage_type,
            variable_parameter_idx,
        ) in iter_flow_screen_required_parameters(args.flow_screen):
            input_schema = _get_input_schema(
                args.flow.client_schema,
                args.flow.server_schema,
                input_path,
                variable_parameter_idx,
            )
            if input_schema.type == "failure":
                return input_schema.error_response

            output_schema = _get_output_schema(
                screen, output_path, variable_parameter_idx, discriminators
            )
            if output_schema.type == "failure":
                return output_schema.error_response

            match_result = _determine_if_appropriate(
                input_schema, output_schema, variable_parameter_idx, usage_type
            )
            if match_result.type == "failure":
                return match_result.error_response

            try:
                deep_extract(args.flow_screen.screen.fixed, output_path)
                return Response(
                    status_code=409,
                    content=StandardErrorResponse[ERROR_409_TYPES](
                        type="screen_input_parameters_redundant",
                        message=f"variable[{variable_parameter_idx}] overwrites fixed value at {pretty_path(output_path)}: remove one, as these are redundant",
                    ).model_dump_json(),
                    headers={"Content-Type": "application/json; charset=utf-8"},
                )
            except KeyError:
                pass

        for enum_path, allowed_values in screen.realizer.iter_enum_discriminators():
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
                            headers={"Content-Type": "application/json; charset=utf-8"},
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
        )

        screen_input_parameters = produce_screen_input_parameters(
            args.flow_screen,
            args.client_parameters,
            args.server_parameters,
            standard_parameters,
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
                json.dumps(args.client_parameters, sort_keys=True),
                json.dumps(args.server_parameters, sort_keys=True),
                json.dumps(args.flow_screen.model_dump(), sort_keys=True),
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
    while remaining:
        nullable = current.get("nullable", False)
        if nullable is not False:
            if len(remaining) > 1:
                return FindSchemaNotFound(
                    type="failure",
                    error_response=Response(
                        status_code=409,
                        content=StandardErrorResponse[ERROR_409_TYPES](
                            type="screen_input_parameters_wont_match",
                            message=f"variable[{variable_parameter_idx}] references {pretty_path(input_path)}, which is nullable at {pretty_path(made_it_to)}",
                        ).model_dump_json(),
                        headers={"Content-Type": "application/json; charset=utf-8"},
                    ),
                )

        current_type = current.get("type")
        if current_type == "object":
            required = current.get("required", [])

            assert isinstance(required, list)
            if remaining[0] not in required:
                return FindSchemaNotFound(
                    type="failure",
                    error_response=Response(
                        status_code=409,
                        content=StandardErrorResponse[ERROR_409_TYPES](
                            type="screen_input_parameters_wont_match",
                            message=f"variable[{variable_parameter_idx}] references {pretty_path(input_path)}, which is not required at {pretty_path(made_it_to)}. You may require it and make it nullable if its the last part of the path",
                        ).model_dump_json(),
                        headers={"Content-Type": "application/json; charset=utf-8"},
                    ),
                )

            properties = current.get("properties", dict())
            assert isinstance(properties, dict)

            nxt = properties.get(remaining[0])
            if nxt is None:
                return FindSchemaNotFound(
                    type="failure",
                    error_response=Response(
                        status_code=409,
                        content=StandardErrorResponse[ERROR_409_TYPES](
                            type="screen_input_parameters_wont_match",
                            message=f"variable[{variable_parameter_idx}] references {pretty_path(input_path)}, which is not in properties at {pretty_path(made_it_to)}",
                        ).model_dump_json(),
                        headers={"Content-Type": "application/json; charset=utf-8"},
                    ),
                )

            current = nxt
            made_it_to.append(remaining.pop(0))
            continue

        if current_type == "array":
            try:
                key_as_int = int(remaining[0])
            except ValueError:
                return FindSchemaNotFound(
                    type="failure",
                    error_response=Response(
                        status_code=409,
                        content=StandardErrorResponse[ERROR_409_TYPES](
                            type="screen_input_parameters_wont_match",
                            message=f"variable[{variable_parameter_idx}] references {pretty_path(input_path)}, which is an array at {pretty_path(made_it_to)}",
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
                            message=f"variable[{variable_parameter_idx}] references {pretty_path(input_path)}, which is an array at {pretty_path(made_it_to)}, but without an items schema",
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
                                f"which is an array at {pretty_path(made_it_to)}, but with too few items (requires {min_items}, "
                                f"but needs to require at least {key_as_int + 1})"
                            ),
                        ).model_dump_json(),
                        headers={"Content-Type": "application/json; charset=utf-8"},
                    ),
                )

            current = items
            made_it_to.append(remaining.pop(0))
            continue

        return FindSchemaNotFound(
            type="failure",
            error_response=Response(
                status_code=409,
                content=StandardErrorResponse[ERROR_409_TYPES](
                    type="screen_input_parameters_wont_match",
                    message=f"variable[{variable_parameter_idx}] references {pretty_path(input_path)}, "
                    f"which is not an object or array (is a {current_type}) at {pretty_path(made_it_to)}",
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
    path: List[str],
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
    made_it_to: List[str] = []
    remaining = path.copy()

    def error_source():
        if variable_parameter_idx == -1:
            return "fixed"
        return f"variable[{variable_parameter_idx}]"

    while remaining:
        current_type = current.get("type")
        if current_type == "object":
            if "x-enum-discriminator" in current:
                discriminated_to_index = discriminators.get(tuple(made_it_to))
                if discriminated_to_index is None:
                    return FindSchemaNotFound(
                        type="failure",
                        error_response=Response(
                            status_code=409,
                            content=StandardErrorResponse[ERROR_409_TYPES](
                                type="screen_input_parameters_wont_match",
                                message=f"{error_source()} targets {pretty_path(path)}, which is an enum discriminator at {pretty_path(made_it_to)}, but was not discriminated in fixed",
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

            properties = current.get("properties", dict())
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
    variable_parameter_idx: int,
    usage_type: Literal["copy", "string_formattable"],
):
    """Determines if its appropriate to take an object described by the input_schema
    and put it into the output_schema.

    Args:
        input_schema (FindSchemaSuccess): The schema of the input
        output_schema (FindSchemaSuccess): The schema of the output
        variable_parameter_idx (int): The index of the variable parameter in the flow screen,
            for error formatting
        usage_type (Literal["copy", "string_formattable"]): The type of usage for the variable parameter
    """
    if not input_schema.safe and not output_schema.safe:
        return IsAppropriateFailure(
            type="failure",
            error_response=Response(
                status_code=409,
                content=StandardErrorResponse[ERROR_409_TYPES](
                    type="screen_is_unsafe",
                    message=f"variable[{variable_parameter_idx}] uses an unsafe input, but the target requires a safe input",
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
            ),
        )

    if usage_type == "string_formattable":
        output_type = output_schema.schema.get("type")
        if output_type != "string":
            return IsAppropriateFailure(
                type="failure",
                error_response=Response(
                    status_code=409,
                    content=StandardErrorResponse[ERROR_409_TYPES](
                        type="screen_input_parameters_wont_match",
                        message=f"variable[{variable_parameter_idx}] produces a string, but the target is a {output_type}",
                    ).model_dump_json(),
                    headers={"Content-Type": "application/json; charset=utf-8"},
                ),
            )
        return IsAppropriateSuccess(type="success")

    if usage_type == "copy":
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
                        message=f"variable[{variable_parameter_idx}] copies to target, but the input is nullable and the target is not",
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
                        message=f"variable[{variable_parameter_idx}] copies to target, but the example of the input doesnt match the output schema: {err}",
                    ).model_dump_json(),
                    headers={"Content-Type": "application/json; charset=utf-8"},
                ),
            )

        return IsAppropriateSuccess(type="success")

    raise ValueError(f"Unsupported usage type: {usage_type}")


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
