from typing import Any, Generator, List, Literal, Tuple, Union, cast, TYPE_CHECKING

if TYPE_CHECKING:
    from lib.client_flows.client_flow_screen import ClientFlowScreen
    from lib.client_flows.screen_cache import ClientScreen

import string

from lib.extract_format_parameter_field_name import extract_format_parameter_field_name
from openapi_schema_validator.validators import OAS30Validator
import jsonschema.exceptions
from dataclasses import dataclass


def check_if_flow_screen_is_safe(
    flow_screen: "ClientFlowScreen", screen: "ClientScreen"
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
    flow_screen: "ClientFlowScreen",
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
    flow_screen: "ClientFlowScreen",
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


@dataclass(frozen=True)
class _State:
    allow_enum_discriminator: bool
    no_default: bool
    """True if it doesnt make sense for this field to have a default value. For example,
    within an array the items cannot have a default value (when would you use that?).
    """


def check_oas_30_schema(
    schema: Any,
    /,
    *,
    require_enum_discriminator: bool = True,
    require_example: bool = False,
    require_default: bool = True,
) -> None:
    """Like OAS30Validator.check_schema but forbids $ref and may include other
    requirements

    Arguments:
        schema (Any): The schema to validate
        require_enum_discriminator (bool): If true, verifies that if the type is `object`
            and `oneOf` is set, then an `x-enum-discriminator` value is set to a string
            which matches a required, non-nullable, string property on each subschema.
        require_example (bool): If True, verifies `example` is set on the schema
            and the example validates against the schema (recursively)
        require_default (bool): If True, for any part that is not required to be present
            a default value must be set.
    """
    # TODO: A custom validator would make more sense here, but this gets the job done
    OAS30Validator.check_schema(schema)

    assert isinstance(schema, dict)

    stack: List[Tuple[dict, List[Union[str, int]], _State]] = [
        (schema, [], _State(allow_enum_discriminator=True, no_default=True))
    ]
    while stack:
        if "$ref" in schema:
            raise jsonschema.exceptions.ValidationError(
                f"at {pretty_path(path)}: cannot have '$ref'"
            )

        subschema, path, state = stack.pop()
        new_state = state
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

        if state.no_default and "default" in subschema:
            raise jsonschema.exceptions.ValidationError(
                f"at {pretty_path(path)}: must not have 'default' here (illogical)"
            )

        if require_default and not state.no_default:
            if "default" not in subschema:
                raise jsonschema.exceptions.ValidationError(
                    f"at {pretty_path(path)}: missing 'default' for potentially unset field"
                )

            try:
                OAS30Validator(subschema).validate(subschema["default"])
            except jsonschema.exceptions.ValidationError as e:
                raise jsonschema.exceptions.ValidationError(
                    f"at {pretty_path(path)}, failed to match 'default': {e}"
                )

        subschema_type = subschema.get("type")
        if subschema_type == "object":
            properties = subschema.get("properties", dict())
            if not isinstance(properties, dict):
                raise jsonschema.exceptions.ValidationError(
                    f"at {pretty_path(path)}: 'properties' must be an object"
                )

            if (require_enum_discriminator and "oneOf" in subschema) or (
                "x-enum-discriminator" in subschema
            ):
                if not state.allow_enum_discriminator:
                    raise jsonschema.exceptions.ValidationError(
                        f"at {pretty_path(path)}: 'x-enum-discriminator' cannot be nested"
                    )
                new_state = _State(
                    allow_enum_discriminator=False, no_default=state.no_default
                )

                oneof = subschema["oneOf"]
                if not isinstance(oneof, list):
                    raise jsonschema.exceptions.ValidationError(
                        f"at {pretty_path(path + ['oneOf'])}: must be an array"
                    )

                seen_values = set()
                enum_discriminator = subschema.get("x-enum-discriminator")
                if not isinstance(enum_discriminator, str):
                    raise jsonschema.exceptions.ValidationError(
                        f"at {pretty_path(path + ['x-enum-discriminator'])}: must be set to a string"
                    )

                if enum_discriminator == "":
                    raise jsonschema.exceptions.ValidationError(
                        f"at {pretty_path(path)}: 'x-enum-discriminator' must not be empty"
                    )

                if "properties" in subschema:
                    raise jsonschema.exceptions.ValidationError(
                        f"at {pretty_path(path)}: 'properties' must not be set when 'x-enum-discriminator' is set on objects (unsupported)"
                    )

                for oneof_idx, inner_schema in enumerate(oneof):
                    inner_path = path + ["oneOf", oneof_idx]
                    if not isinstance(inner_schema, dict):
                        raise jsonschema.exceptions.ValidationError(
                            f"at {pretty_path(inner_path)}: dict expected"
                        )

                    if inner_schema.get("type") != "object":
                        raise jsonschema.exceptions.ValidationError(
                            f"at {pretty_path(inner_path)}: type 'object' expected"
                        )

                    inner_properties = inner_schema.get("properties", dict())
                    if not isinstance(inner_properties, dict):
                        raise jsonschema.exceptions.ValidationError(
                            f"at {pretty_path(inner_path)}: 'properties' must be an object"
                        )

                    inner_required = inner_schema.get("required", list())
                    if not isinstance(inner_required, list):
                        raise jsonschema.exceptions.ValidationError(
                            f"at {pretty_path(inner_path)}: 'required' must be an array"
                        )

                    if enum_discriminator not in inner_required:
                        raise jsonschema.exceptions.ValidationError(
                            f"at {pretty_path(inner_path)}: 'required' must include '{enum_discriminator}' (via x-enum-discriminator)"
                        )

                    inner_descrim_schema = inner_properties.get(enum_discriminator)
                    inner_descrim_path = inner_path + ["properties", enum_discriminator]
                    if not isinstance(inner_descrim_schema, dict):
                        raise jsonschema.exceptions.ValidationError(
                            f"at {pretty_path(inner_descrim_path)}: must be a dict (via x-enum-discriminator)"
                        )

                    if inner_descrim_schema.get("type") != "string":
                        raise jsonschema.exceptions.ValidationError(
                            f"at {pretty_path(inner_descrim_path)}: must have type string (via x-enum-discriminator)"
                        )

                    if inner_descrim_schema.get("nullable") is True:
                        raise jsonschema.exceptions.ValidationError(
                            f"at {pretty_path(inner_descrim_path)}: must not be nullable (via x-enum-discriminator)"
                        )

                    inner_descrim_schema_enum = inner_descrim_schema.get("enum")
                    if not isinstance(inner_descrim_schema_enum, list):
                        raise jsonschema.exceptions.ValidationError(
                            f"at {pretty_path(inner_descrim_path)}: must have an enum list (via x-enum-discriminator)"
                        )

                    if len(inner_descrim_schema_enum) != 1:
                        raise jsonschema.exceptions.ValidationError(
                            f"at {pretty_path(inner_descrim_path + ['enum'])}: must have 1 entry (via x-enum-discriminator)"
                        )

                    if not isinstance(inner_descrim_schema_enum[0], str):
                        raise jsonschema.exceptions.ValidationError(
                            f"at {pretty_path(inner_descrim_path + ['enum', 0])}: must have a string enum (via x-enum-discriminator)"
                        )

                    if inner_descrim_schema_enum[0] == "":
                        raise jsonschema.exceptions.ValidationError(
                            f"at {pretty_path(inner_descrim_path + ['enum', 0])}: must not be empty (via x-enum-discriminator)"
                        )

                    if inner_descrim_schema_enum[0] in seen_values:
                        raise jsonschema.exceptions.ValidationError(
                            f"at {pretty_path(inner_descrim_path + ['enum', 0])}: must be unique within oneOf (via x-enum-discriminator)"
                        )

                    seen_values.add(inner_descrim_schema_enum[0])

            required_list = subschema.get("required", list())
            if not isinstance(required_list, list):
                raise jsonschema.exceptions.ValidationError(
                    f"at {pretty_path(path)}: 'required' must be an array"
                )
            if not all(isinstance(x, str) for x in required_list):
                raise jsonschema.exceptions.ValidationError(
                    f"at {pretty_path(path)}: 'required' must be an array of strings"
                )

            required_set = frozenset(required_list)
            if len(required_set) != len(required_list):
                raise jsonschema.exceptions.ValidationError(
                    f"at {pretty_path(path)}: 'required' must be unique"
                )

            for key, value in properties.items():
                stack.append(
                    (
                        value,
                        path + ["properties", key],
                        _State(
                            allow_enum_discriminator=new_state.allow_enum_discriminator,
                            no_default=key in required_set,
                        ),
                    )
                )
        elif subschema_type == "array":
            items = subschema.get("items")
            if not isinstance(items, dict):
                raise jsonschema.exceptions.ValidationError(
                    f"at {pretty_path(path)}: 'items' must be an object"
                )

            stack.append(
                (
                    items,
                    path + ["items"],
                    _State(allow_enum_discriminator=False, no_default=True),
                )
            )

        if "allOf" in subschema:
            for idx, value in enumerate(subschema["allOf"]):
                stack.append(
                    (
                        value,
                        path + ["allOf", idx],
                        _State(allow_enum_discriminator=False, no_default=True),
                    )
                )

        if "anyOf" in subschema:
            for idx, value in enumerate(subschema["anyOf"]):
                stack.append(
                    (
                        value,
                        path + ["anyOf", idx],
                        _State(allow_enum_discriminator=False, no_default=True),
                    )
                )

        if "oneOf" in subschema:
            for idx, value in enumerate(subschema["oneOf"]):
                stack.append(
                    (
                        value,
                        path + ["oneOf", idx],
                        _State(allow_enum_discriminator=False, no_default=True),
                    )
                )

        if "not" in subschema:
            stack.append(
                (
                    subschema["not"],
                    path + ["not"],
                    _State(allow_enum_discriminator=False, no_default=True),
                )
            )


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


def extract_schema_default_value(*, schema: dict, fixed: dict, path: List[str]) -> Any:
    """
    Given that you have the given openapi 3.0.3 schema, and you have filled the
    object `fixed`, determines what the effective value is at the given path.

    For example, if

    ```py
    schema = {
        "type": "object",
        "properties": {
            "simple": {
                "type": "string",
                "default": "top-default-simple"
            },
            "nested": {
                "type": "object",
                "default": { "key": "top-default-nested" },
                "properties": {
                    "key": {
                        "type": "string",
                        "default": "bottom-default"
                    }
                }
            }
        }
    }
    ```

    then

    ```py
    extract_schema_default_value(schema=schema, fixed={}, path=["simple"]) == "top-default-simple"
    extract_schema_default_value(schema=schema, fixed={}, path=["nested", "key"]) == "top-default-nested"
    extract_schema_default_value(schema=schema, fixed={"nested": {}}, path=["nested", "key"]) == "bottom-default"
    ```

    i.e., we take from fixed until there is nothing left, and then we fill in defaults from
    the schema.
    """
    src = fixed
    src_schema = schema
    src_schema_path = []

    idx = 0
    while idx < len(path):
        item = path[idx]

        if src_schema.get("type") != "object":
            raise KeyError(
                f"Expected object in schema at {pretty_path(src_schema_path)} to extract {pretty_path(path)}, got {src_schema}"
            )

        if "properties" not in src_schema:
            if "oneOf" in src_schema and "x-enum-discriminator" in src_schema:
                discriminator = src_schema["x-enum-discriminator"]
                assert isinstance(
                    discriminator, str
                ), f"{discriminator=} at {pretty_path(path[:idx + 1])} to extract {pretty_path(path)}"

                if discriminator not in src:
                    raise KeyError(
                        f"Expected {discriminator} in {src} at {pretty_path(path[:idx + 1])} to extract {pretty_path(path)}"
                    )

                oneof = src_schema["oneOf"]
                assert isinstance(
                    oneof, list
                ), f"expected list at {pretty_path(src_schema_path + ['oneOf'])} to extract {pretty_path(path)}"
                for oneof_idx, opt in enumerate(oneof):
                    assert isinstance(
                        opt, dict
                    ), f"expected dict at {pretty_path(path[:idx + 1] + ['oneOf', oneof_idx])} to extract {pretty_path(path)}"
                    opt_properties = opt.get("properties", dict())
                    assert isinstance(
                        opt_properties, dict
                    ), f"expected dict at {pretty_path(path[:idx + 1] + ['oneOf', oneof_idx, 'properties'])} to extract {pretty_path(path)}"
                    opt_discriminator = opt_properties.get(discriminator)
                    assert isinstance(
                        opt_discriminator, dict
                    ), f"expected dict at {pretty_path(path[:idx + 1] + ['oneOf', oneof_idx, 'properties', discriminator])} to extract {pretty_path(path)}"
                    opt_discriminator_enum = opt_discriminator.get("enum")
                    assert isinstance(
                        opt_discriminator_enum, list
                    ), f"expected list at {pretty_path(path[:idx + 1] + ['oneOf', oneof_idx, 'properties', discriminator, 'enum'])} to extract {pretty_path(path)}"
                    if src[discriminator] in opt_discriminator_enum:
                        src_schema = opt
                        src_schema_path = src_schema_path + ["oneOf", oneof_idx]
                        break
                else:
                    raise KeyError(
                        f"Expected {discriminator} in {src} to match oneOf at {pretty_path(src_schema_path)} to extract {pretty_path(path)}"
                    )

                if item not in src:
                    break
            else:
                raise KeyError(
                    f"Expected properties in schema at {pretty_path(src_schema_path)} to extract {pretty_path(path)}"
                )

        if item not in src_schema["properties"]:
            raise KeyError(
                f"Expected {item} in {src_schema['properties']} at {pretty_path(src_schema_path)} to extract {pretty_path(path)}"
            )

        src_schema = src_schema["properties"][item]
        src_schema_path = src_schema_path + ["properties", item]
        if item not in src:
            break

        src = src[item]
        idx += 1

    if idx == len(path):
        return src

    if "default" not in src_schema:
        raise KeyError(
            f"Expected default in schema at {pretty_path(src_schema_path)} to extract {pretty_path(path)}"
        )

    idx += 1  # by going into default we've effectively consumed item
    src = src_schema["default"]
    src_path = src_schema_path + ["default"]
    while idx < len(path):
        item = path[idx]

        if item not in src:
            raise KeyError(
                f"Expected {item} in {src} at {pretty_path(src_path)} to extract {pretty_path(path)}"
            )

        src = src[item]
        src_path = src_path + [item]
        idx += 1

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
