from typing import Any, Generator, List, Literal, Tuple, Union, cast

from lib.client_flows.client_flow_screen import ClientFlowScreen
from lib.client_flows.screen_cache import ClientScreen

import string

from lib.extract_format_parameter_field_name import extract_format_parameter_field_name
from openapi_schema_validator.validators import OAS30Validator
import jsonschema.exceptions


def check_if_flow_screen_is_safe(
    flow_screen: ClientFlowScreen, screen: ClientScreen
) -> bool:
    """Determines if the given client flow screen is safe to realize.

    This endpoint is primarily intended for reference. For performance it might
    be reasonable to assume that client flows are configured correctly and skip
    this check.
    """
    fmt = string.Formatter()
    for variable_parameter in flow_screen.screen.variable:
        if variable_parameter.type == "copy":
            if variable_parameter.input_path[
                0
            ] != "server" and not screen.realizer.is_safe(
                variable_parameter.output_path
            ):
                return False
        elif variable_parameter.type == "string_format":
            if screen.realizer.is_safe(variable_parameter.output_path):
                continue

            for part in fmt.parse(variable_parameter.format):
                if part[1] is not None and not part[1].startswith("server["):
                    return False
        else:
            return False
    return True


def iter_flow_screen_required_parameters(
    flow_screen: ClientFlowScreen,
) -> Generator[
    Tuple[List[str], List[str], Literal["string_formattable", "copy"], int], None, None
]:
    """Iterates which parameters, if any, are required to trigger a flow
    with the given flow screen. This is used for verifying that a flows
    client_schema and server_schema are sufficient to trigger the flow.

    Yields items like `(["standard", "user", "name"], ["foo"], "string_formattable" or None)`
    """
    fmt = string.Formatter()
    for idx, variable_parameter in enumerate(flow_screen.screen.variable):
        if variable_parameter.type == "copy":
            yield variable_parameter.input_path, variable_parameter.output_path, "copy", idx
        elif variable_parameter.type == "string_format":
            for part in fmt.parse(variable_parameter.format):
                if part[1] is not None:
                    yield extract_format_parameter_field_name(
                        part[1]
                    ), variable_parameter.output_path, "string_formattable", idx
        else:
            raise ValueError(f"Unknown parameter {variable_parameter}")


def produce_screen_input_parameters(
    flow_screen: ClientFlowScreen,
    flow_client_parameters: Any,
    flow_server_parameters: Any,
    standard_parameters: Any,
) -> Any:
    """Determines the input parameters for the actual client screen based on the client
    flow. This should be done just before realizing the screen since the standard parameters
    can drift over time (e.g., when the user updates their name)
    """
    result = deep_copy(flow_screen.screen.fixed)

    copy_dict = {
        "server": flow_server_parameters,
        "client": flow_client_parameters,
        "standard": standard_parameters,
    }

    for variable_parameter in flow_screen.screen.variable:
        assert (
            variable_parameter.output_path
        ), f"empty output path: {variable_parameter} for flow screen {flow_screen.model_dump_json(indent=2)}"
        if variable_parameter.type == "copy":
            val = deep_extract(copy_dict, variable_parameter.input_path)
            deep_set(result, variable_parameter.output_path, val)
        elif variable_parameter.type == "string_format":
            formatted = variable_parameter.format.format(
                server=flow_server_parameters,
                client=flow_client_parameters,
                standard=standard_parameters,
            )
            deep_set(result, variable_parameter.output_path, formatted)
        else:
            raise ValueError(f"Unsupported: {variable_parameter}")

    return result


def check_oas_30_schema(schema: Any, /, *, require_example: bool = False) -> None:
    """Like OAS30Validator.check_schema but forbids $ref and may include other
    requirements

    Arguments:
        schema (Any): The schema to validate
        require_example (bool): If True, verifies `example` is set on the schema
            and the example validates against the schema (recursively)
    """
    # TODO: A custom validator would make more sense here, but this gets the job done
    OAS30Validator.check_schema(schema)

    assert isinstance(schema, dict)

    stack: List[Tuple[dict, List[Union[str, int]]]] = [(schema, [])]
    while stack:
        if "$ref" in schema:
            raise jsonschema.exceptions.ValidationError(
                f"at {pretty_path(path)}: cannot have '$ref'"
            )

        subschema, path = stack.pop()
        if require_example:
            if "example" not in subschema:
                raise jsonschema.exceptions.ValidationError(
                    f"at {pretty_path(path)}: missing 'example'"
                )

            try:
                OAS30Validator(subschema).validate(subschema["example"])
            except jsonschema.exceptions.ValidationError as e:
                raise jsonschema.exceptions.ValidationError(
                    f"at {pretty_path(path)}, failed to match 'example': {e}"
                )

        subschema_type = subschema.get("type")
        if subschema_type == "object":
            properties = subschema.get("properties", dict())
            if not isinstance(properties, dict):
                raise jsonschema.exceptions.ValidationError(
                    f"at {pretty_path(path)}: 'properties' must be an object"
                )

            for key, value in properties.items():
                stack.append((value, path + ["properties", key]))
        elif subschema_type == "array":
            items = subschema.get("items")
            if not isinstance(items, dict):
                raise jsonschema.exceptions.ValidationError(
                    f"at {pretty_path(path)}: 'items' must be an object"
                )

            stack.append((items, path + ["items"]))

        if "allOf" in subschema:
            for idx, value in enumerate(subschema["allOf"]):
                stack.append((value, path + ["allOf", idx]))

        if "anyOf" in subschema:
            for idx, value in enumerate(subschema["anyOf"]):
                stack.append((value, path + ["anyOf", idx]))

        if "oneOf" in subschema:
            for idx, value in enumerate(subschema["oneOf"]):
                stack.append((value, path + ["oneOf", idx]))

        if "not" in subschema:
            stack.append((subschema["not"], path + ["not"]))


def pretty_path(path: Union[List[Union[str, int]], List[str], List[int]]) -> str:
    """Converts a path of the form ["server", 0, "name"] to a string like "$.server[0].name"."""
    parts = ["$"]
    for item in path:
        if isinstance(item, int):
            parts.append(f"[{item}]")
        else:
            parts.append(f".{item}")
    return "".join(parts)


def deep_extract(original: dict, path: List[str]) -> Any:
    src = original
    for item in path:
        src = src[item]
    return src


def deep_set(original: dict, path: List[str], value: Any) -> None:
    assert path, f"_deep_set empty path on {original}, value {value}, path {path}"
    src = original
    for item in path[:-1]:
        src = src[item]
    src[path[-1]] = value


def deep_copy(original: Any) -> Any:
    """Performs a deep copy of the given value assuming its json-like."""
    if isinstance(original, list):
        result = list()
        if len(original) == 0:
            return result
    elif isinstance(original, dict):
        result = dict()
    else:
        return original

    stack = cast(
        List[Union[Tuple[dict, dict], Tuple[list, list]]], [(original, result)]
    )
    while stack:
        nxt = stack.pop()
        if isinstance(nxt[0], dict):
            src, dst = cast(Tuple[dict, dict], nxt)
            for key, val in src.items():
                if isinstance(val, dict):
                    dst[key] = dict()
                    stack.append((val, dst[key]))
                elif isinstance(val, list):
                    dst[key] = list()
                    if len(val) > 0:
                        stack.append((val, dst[key]))
                else:
                    dst[key] = val
        else:
            src, dst = cast(Tuple[list, list], nxt)
            val = src[len(dst)]
            if isinstance(val, dict):
                tmp = dict()
                dst.append(tmp)
                stack.append((val, tmp))
            elif isinstance(val, list):
                tmp = list()
                dst.append(tmp)
                if len(val) > 0:
                    stack.append((val, tmp))
            else:
                dst.append(val)
            if len(dst) < len(src):
                stack.append((src, dst))
    return result
