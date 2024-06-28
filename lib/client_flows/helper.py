import json
from typing import (
    Any,
    Dict,
    Generator,
    List,
    Literal,
    Optional,
    Tuple,
    Union,
    cast,
    TYPE_CHECKING,
)

from courses.lib.get_external_course_from_row import (
    ExternalCourseRow,
    create_standard_external_course_query,
    get_external_course_from_row,
)
from itgs import Itgs
from journeys.lib.read_one_external import read_one_external
from lib.client_flows.client_flow_screen import (
    ClientFlowScreenVariableInput,
)
from lib.client_flows.special_index import SpecialIndex
from response_utils import response_to_bytes

if TYPE_CHECKING:
    from lib.client_flows.flow_cache import ClientFlow
    from lib.client_flows.client_flow_screen import ClientFlowScreen
    from lib.client_flows.screen_cache import ClientScreen

import string

from lib.extract_format_parameter_field_name import extract_format_parameter_field_name
from openapi_schema_validator.validators import OAS30Validator
import jsonschema.exceptions
from dataclasses import dataclass
from loguru import logger


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
        elif variable_parameter.type == "extract":
            if variable_parameter.input_path[0] != "server":
                return False
        else:
            return False
    return True


@dataclass(frozen=True)
class FlowScreenRequiredParameter:
    input_path: List[str]
    output_path: List[str]
    usage_type: Literal["string_formattable", "copy", "extract"]
    idx: int
    variable_parameter: ClientFlowScreenVariableInput


def iter_flow_screen_required_parameters(
    flow_screen: "ClientFlowScreen",
) -> Generator[FlowScreenRequiredParameter, None, None]:
    """Iterates which parameters, if any, are required to trigger a flow
    with the given flow screen. This is used for verifying that a flows
    client_schema and server_schema are sufficient to trigger the flow.
    """
    fmt = string.Formatter()
    for idx, variable_parameter in enumerate(flow_screen.screen.variable):
        if variable_parameter.type == "copy":
            yield FlowScreenRequiredParameter(
                variable_parameter.input_path,
                variable_parameter.output_path,
                "copy",
                idx,
                variable_parameter,
            )
        elif variable_parameter.type == "string_format":
            for part in fmt.parse(variable_parameter.format):
                if part[1] is not None:
                    yield FlowScreenRequiredParameter(
                        extract_format_parameter_field_name(part[1]),
                        variable_parameter.output_path,
                        "string_formattable",
                        idx,
                        variable_parameter,
                    )
        elif variable_parameter.type == "extract":
            yield FlowScreenRequiredParameter(
                variable_parameter.input_path,
                variable_parameter.output_path,
                "extract",
                idx,
                variable_parameter,
            )
        else:
            raise ValueError(f"Unknown parameter {variable_parameter}")


@dataclass(frozen=True)
class TransformFlowServerParametersSuccess:
    type: Literal["success"]
    transformed_server_parameters: Any
    transformed_flow_screen: "ClientFlowScreen"


@dataclass
class TransformFlowServerParametersSkip:
    type: Literal["skip"]


TransformFlowServerParametersResult = Union[
    TransformFlowServerParametersSuccess,
    TransformFlowServerParametersSkip,
]


async def handle_trigger_time_transformations(
    itgs: Itgs,
    /,
    *,
    flow: "ClientFlow",
    flow_screen: "ClientFlowScreen",
    flow_server_parameters: Any,
) -> TransformFlowServerParametersResult:
    """Manages any trigger-time transformations that occur to the given flow screen.
    This can transform both the flow server parameters that are sent (realizing values
    that require extraction) and the actual variable parameters for the flow screen
    (to reference the extracted values instead of the original server parameters).

    These transformations are:
    - `extract`: Suppose a flow wants to show a video interstitial containing the series
      preview video. The flow would receive the series uid in the server parameters,
      but can't forward that directly to the video interstitial screen which just wants
      a content_uid.

      To accomplish this, the flow screen can use the variable parameter type `extract`
      with the input path being `["server", "series"]`, the extraction path being
      `["uid"]` and the output path being `["video"]`. This will cause that flow
      screen to be pushed onto the users client queue with the server parameter for
      the flow transformed from the series uid to the content uid of the video, and
      the variable input type `extract` is treated like copy at peek time.
    - `string_format`: Handles automatic extraction in the same was as `extract`.
      Further, If `e164` is used as the format spec for one of the inputs, after
      extraction, we will convert an E.164 phone number with a U.S country code
      to e.g. +1 555-555-5555.
    """
    fmt = string.Formatter()

    new_server_parameters = None
    new_variable_parameters = cast(Optional[List[ClientFlowScreenVariableInput]], None)

    # we don't currently have a built-in cache for courses, so in case we are repeatedly
    # extracting from the same course (common), this avoids repeated requests
    courses_by_uid: Dict[str, dict] = {}

    for variable_parameter_idx, variable_parameter in enumerate(
        flow_screen.screen.variable
    ):
        if variable_parameter.type == "extract":
            if new_server_parameters is None:
                new_server_parameters = deep_copy(flow_server_parameters)

            assert (
                variable_parameter.input_path[0] == "server"
            ), "not an extractable target"

            target_schema, target_value = deep_extract_value_and_subschema(
                flow.server_schema_raw,
                flow_server_parameters,
                variable_parameter.input_path[1:],
            )
            target_type = target_schema.get("type")
            if target_type == "null" or target_value is None:
                if variable_parameter.skip_if_missing:
                    return TransformFlowServerParametersSkip(type="skip")
                deep_set(
                    new_server_parameters,
                    ["__extracted"] + variable_parameter.output_path,
                    None,
                )
                continue

            assert target_type == "string", "not an extractable target"
            target_format = target_schema.get("format")
            assert isinstance(
                target_format, str
            ), "not an extractable target (are you missing format?)"
            await _handle_extraction(
                itgs,
                target_value=target_value,
                target_format=target_format,
                courses_by_uid=courses_by_uid,
                extracted_path=variable_parameter.extracted_path,
                server_parameter_path=["__extracted"] + variable_parameter.output_path,
                new_server_parameters=new_server_parameters,
            )
        elif variable_parameter.type == "string_format":
            new_format_parts = []
            replaced_part = False
            for part_idx, part in enumerate(fmt.parse(variable_parameter.format)):
                new_format_parts.append(part)

                if part[1] is None:
                    continue
                full_path = extract_format_parameter_field_name(part[1])
                if full_path[0] != "server":
                    continue
                split_path = split_input_path_and_extract_path(
                    flow.server_schema_raw,
                    flow_server_parameters,
                    full_path[1:],
                )
                if split_path.type == "not_a_split":
                    if split_path.target_schema.get("type") == "null":
                        # if we did nothing this might result in 'NoneType' object is not subscriptable
                        replaced_part = True
                        new_format_parts[part_idx] = (
                            part[0],
                            "{server[__extracted][__none]}",
                            part[2],
                            part[3],
                        )
                        if new_server_parameters is None:
                            new_server_parameters = deep_copy(flow_server_parameters)
                        deep_set(new_server_parameters, ["__extracted", "__none"], None)
                    continue

                target_format = split_path.target_schema.get("format")
                assert isinstance(
                    target_format, str
                ), "not an extractable target (are you missing format?)"

                replaced_part = True
                if new_server_parameters is None:
                    new_server_parameters = deep_copy(flow_server_parameters)
                server_parameter_path = (
                    ["__extracted"] + variable_parameter.output_path + [f"_{part_idx}"]
                )
                new_format_parts[part_idx] = (
                    part[0].replace("{", "{{").replace("}", "}}"),
                    "{server" + "".join(f"[{x}]" for x in server_parameter_path) + "}",
                    part[2],
                    part[3],
                )

                await _handle_extraction(
                    itgs,
                    target_value=split_path.target_value,
                    target_format=target_format,
                    courses_by_uid=courses_by_uid,
                    extracted_path=split_path.extracted_path,
                    server_parameter_path=server_parameter_path,
                    new_server_parameters=new_server_parameters,
                )

            for part_idx, part in enumerate(new_format_parts):
                if part[2] != "e164":
                    continue

                full_path = extract_format_parameter_field_name(part[1])
                if full_path[0] != "server":
                    raise ValueError(
                        f"unsupported format {part[2]} for non-server path {full_path}"
                    )

                replaced_part = True
                if new_server_parameters is None:
                    new_server_parameters = deep_copy(flow_server_parameters)

                server_parameter_path = (
                    ["__bonus_format_specs", "e164"]
                    + variable_parameter.output_path
                    + [f"_{part_idx}"]
                )
                value = deep_extract(new_server_parameters, full_path[1:])

                assert isinstance(
                    value, str
                ), f"expected string for e164 format, got {value!r}"
                if value.startswith("+1") and len(value) == 12:
                    value = f"+1 {value[2:5]}-{value[5:8]}-{value[8:12]}"

                deep_set(new_server_parameters, server_parameter_path, value)
                new_format_parts[part_idx] = (
                    part[0],
                    "{server" + "".join(f"[{x}]" for x in server_parameter_path) + "}",
                    None,
                    part[3],
                )

            if replaced_part:
                rebuilt_format_string = "".join(
                    part[0]
                    + (part[1] if part[1] else "")
                    + (f":{part[2]}" if part[2] else "")
                    + (f"!{part[3]}" if part[3] else "")
                    for part in new_format_parts
                )
                logger.debug(
                    f"replaced string format {variable_parameter.format!r} with {rebuilt_format_string!r} using parts {new_format_parts} while transforming server parameters"
                )
                if new_variable_parameters is None:
                    new_variable_parameters = flow_screen.screen.variable.copy()
                new_variable_parameters[variable_parameter_idx] = (
                    variable_parameter.model_copy(
                        update={"format": rebuilt_format_string}
                    )
                )

    new_flow_screen = flow_screen
    if new_variable_parameters is not None:
        new_flow_screen = new_flow_screen.model_copy(
            update={
                "screen": new_flow_screen.screen.model_copy(
                    update={"variable": new_variable_parameters}
                )
            }
        )

    return TransformFlowServerParametersSuccess(
        type="success",
        transformed_server_parameters=(
            flow_server_parameters
            if new_server_parameters is None
            else new_server_parameters
        ),
        transformed_flow_screen=new_flow_screen,
    )


async def _handle_course_extraction(
    itgs: Itgs,
    /,
    *,
    target_value: str,
    courses_by_uid: Dict[str, dict],
    extracted_path: Union[List[Union[str, int]], List[str], List[int]],
    server_parameter_path: Union[List[Union[str, int]], List[str], List[int]],
    new_server_parameters: Dict[str, Any],
) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor("none")
    query, qargs = create_standard_external_course_query(None)
    response = await cursor.execute(
        query + " WHERE courses.uid=?", qargs + [target_value]
    )
    if not response.results:
        raise ValueError(f"missing course {target_value}")

    course_dumped = courses_by_uid.get(target_value)
    if course_dumped is None:
        course = await get_external_course_from_row(
            itgs,
            user_sub=None,
            row=ExternalCourseRow(*response.results[0]),
            skip_jwts=True,
            has_entitlement=False,
        )
        course_dumped = course.model_dump()
        courses_by_uid[target_value] = course_dumped

    extracted = deep_extract(course_dumped, extracted_path)
    deep_set(
        new_server_parameters,
        server_parameter_path,
        extracted,
    )
    logger.debug(
        f"extracted {pretty_path(extracted_path)} from course uid {target_value} and stored {extracted=} at {pretty_path(server_parameter_path)} while transforming server parameters"
    )


async def _handle_journey_extraction(
    itgs: Itgs,
    /,
    *,
    target_value: str,
    extracted_path: Union[List[Union[str, int]], List[str], List[int]],
    server_parameter_path: Union[List[Union[str, int]], List[str], List[int]],
    new_server_parameters: Dict[str, Any],
):
    journey_response = await read_one_external(itgs, journey_uid=target_value, jwt="")
    if journey_response is None:
        raise ValueError(f"missing journey {target_value}")
    journey_bytes = await response_to_bytes(journey_response)
    journey_dumped = json.loads(journey_bytes)
    extracted = deep_extract(journey_dumped, extracted_path)
    deep_set(
        new_server_parameters,
        server_parameter_path,
        extracted,
    )
    logger.debug(
        f"extracted {pretty_path(extracted_path)} from journey uid {target_value} and stored {extracted=} at {pretty_path(server_parameter_path)} while transforming server parameters"
    )


async def _handle_extraction(
    itgs: Itgs,
    /,
    *,
    target_value: str,
    target_format: str,
    courses_by_uid: Dict[str, dict],
    extracted_path: Union[List[Union[str, int]], List[str], List[int]],
    server_parameter_path: Union[List[Union[str, int]], List[str], List[int]],
    new_server_parameters: Dict[str, Any],
):
    if target_format == "course_uid":
        await _handle_course_extraction(
            itgs,
            target_value=target_value,
            courses_by_uid=courses_by_uid,
            extracted_path=extracted_path,
            server_parameter_path=server_parameter_path,
            new_server_parameters=new_server_parameters,
        )
    elif target_format == "journey_uid":
        await _handle_journey_extraction(
            itgs,
            target_value=target_value,
            extracted_path=extracted_path,
            server_parameter_path=server_parameter_path,
            new_server_parameters=new_server_parameters,
        )
    else:
        raise ValueError(f"unsupported format for extraction {target_format}")


def produce_screen_input_parameters(
    *,
    flow_screen: "ClientFlowScreen",
    flow_client_parameters: Any,
    transformed_flow_server_parameters: Any,
    standard_parameters: Any,
) -> Any:
    """Determines the input parameters for the actual client screen based on the client
    flow. This should be done just before realizing the screen since the standard parameters
    can drift over time (e.g., when the user updates their name)
    """
    result = deep_copy(flow_screen.screen.fixed)

    copy_dict = {
        "server": transformed_flow_server_parameters,
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
                server=transformed_flow_server_parameters,
                client=flow_client_parameters,
                standard=standard_parameters,
            )
            deep_set(result, variable_parameter.output_path, formatted)
        elif variable_parameter.type == "extract":
            # At this point the extraction has already occurred, so we can just copy
            val = deep_extract(
                copy_dict, ["server", "__extracted"] + variable_parameter.output_path
            )
            deep_set(result, variable_parameter.output_path, val)
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
                    _State(
                        allow_enum_discriminator=new_state.allow_enum_discriminator,
                        no_default=True,
                    ),
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


def pretty_path(
    path: Union[
        List[Union[str, int, SpecialIndex]],
        List[Union[str, int]],
        List[Union[str, SpecialIndex]],
        List[str],
        List[int],
        List[SpecialIndex],
    ],
    /,
    *,
    no_start: bool = False,
) -> str:
    """Converts a path of the form ["server", 0, "name"] to a string like "$.server[0].name"."""
    parts = ["$"] if not no_start else []
    for item in path:
        if item == SpecialIndex.ARRAY_INDEX:
            parts.append("[*]")
        elif isinstance(item, int):
            parts.append(f"[{item}]")
        else:
            parts.append(f".{item}")
    return "".join(parts)


def deep_extract_value_and_subschema(
    schema: dict, value: Any, path: Union[List[Union[str, int]], List[str], List[int]]
) -> Tuple[dict, Any]:
    """Extracts the schema and value at the given path from the schema and value
    given. This works on oseh-extended openapi 3.0.3 schemas, e.g., with
    x-enum-discriminator used whenever anyOf is used, etc.
    """
    idx = 0
    subschema = schema
    subvalue = value
    schema_path_to_here = []

    while True:
        if idx == len(path):
            return subschema, subvalue

        assert isinstance(
            subschema, dict
        ), f"{subschema=} should be a dict at {pretty_path(schema_path_to_here)} to extract {pretty_path(path)}"

        if subschema.get("nullable", False) is True and subvalue is None:
            return {"type": "null"}, None

        part_type = subschema.get("type")
        if part_type == "object":
            assert isinstance(
                subvalue, dict
            ), f"{subvalue=} should be a dict at {pretty_path(schema_path_to_here)} to extract {pretty_path(path)}"

            if "x-enum-discriminator" in subschema:
                discriminator = subschema["x-enum-discriminator"]
                assert isinstance(
                    discriminator, str
                ), f"string expected at {pretty_path(schema_path_to_here + ['x-enum-discriminator'])} to extract {pretty_path(path)}"
                assert (
                    discriminator in subvalue
                ), f"{discriminator=} not in {subvalue=} at {pretty_path(schema_path_to_here)} to extract {pretty_path(path)}"

                discrim_value = subvalue[discriminator]
                assert isinstance(
                    discrim_value, str
                ), f"string expected at {pretty_path(schema_path_to_here + ['x-enum-discriminator'])} to extract {pretty_path(path)}"

                one_of = subschema["oneOf"]
                assert isinstance(
                    one_of, list
                ), f"list expected at {pretty_path(schema_path_to_here + ['oneOf'])} to extract {pretty_path(path)}"
                for one_of_idx, one_of_schema in enumerate(one_of):
                    assert isinstance(
                        one_of_schema, dict
                    ), f"dict expected at {pretty_path(schema_path_to_here + ['oneOf', one_of_idx])} to extract {pretty_path(path)}"
                    assert (
                        one_of_schema.get("type") == "object"
                    ), f"'object' expected at {pretty_path(schema_path_to_here + ['oneOf', one_of_idx, 'type'])} to extract {pretty_path(path)}"
                    one_of_properties = one_of_schema.get("properties", dict())
                    assert isinstance(
                        one_of_properties, dict
                    ), f"dict expected at {pretty_path(schema_path_to_here + ['oneOf', one_of_idx, 'properties'])} to extract {pretty_path(path)}"
                    assert (
                        discriminator in one_of_properties
                    ), f"{discriminator=} not in {one_of_properties=} at {pretty_path(schema_path_to_here)} to extract {pretty_path(path)}"

                    oneof_discrim = one_of_properties[discriminator]
                    assert isinstance(
                        oneof_discrim, dict
                    ), f"dict expected at {pretty_path(schema_path_to_here + ['oneOf', one_of_idx, 'properties', discriminator])} to extract {pretty_path(path)}"
                    assert (
                        oneof_discrim.get("type") == "string"
                    ), f"string expected at {pretty_path(schema_path_to_here + ['oneOf', one_of_idx, 'properties', discriminator])} to extract {pretty_path(path)}"
                    oneof_discrim_enum = oneof_discrim.get("enum")
                    assert isinstance(
                        oneof_discrim_enum, list
                    ), f"list expected at {pretty_path(schema_path_to_here + ['oneOf', one_of_idx, 'properties', discriminator, 'enum'])} to extract {pretty_path(path)}"
                    if discrim_value in oneof_discrim_enum:
                        continue

                    subschema = one_of_schema
                    schema_path_to_here.extend(["oneOf", one_of_idx])
                    break
                else:
                    assert (
                        False
                    ), f"no oneOf schema matched x-enum-discriminator {discriminator!r} {discrim_value=} at {pretty_path(schema_path_to_here)} to extract {pretty_path(path)}"
                continue

            part = path[idx]
            assert isinstance(
                part, str
            ), f"{part=} should be a string at {pretty_path(path[:idx + 1])} to match object schema at {pretty_path(schema_path_to_here)}"
            props = subschema.get("properties", dict())
            assert isinstance(
                props, dict
            ), f"{props=} at {pretty_path(schema_path_to_here)} to extract {pretty_path(path)}"
            assert (
                part in props
            ), f"{part=} not in {props=} at {pretty_path(schema_path_to_here)} to extract {pretty_path(path)}"
            assert isinstance(
                subvalue, dict
            ), f"{subvalue=} should be a dict at {pretty_path(path[:idx + 1])} to extract {pretty_path(path)}"

            if part not in subvalue:
                required = subschema.get("required", list())
                assert isinstance(
                    required, list
                ), f"{required=} should be a list at {pretty_path(schema_path_to_here)} to extract {pretty_path(path)}"
                if part not in required:
                    return {"type": "null"}, None
                assert (
                    False
                ), f"{part=} not in {subvalue=} at {pretty_path(path[:idx + 1])} to extract {pretty_path(path)}, despite required"

            subschema = props[part]
            schema_path_to_here.extend(["properties", part])
            subvalue = subvalue[part]
            idx += 1
            continue

        if part_type == "array":
            assert isinstance(
                subvalue, list
            ), f"{subvalue=} should be a list at {pretty_path(schema_path_to_here)} to extract {pretty_path(path)}"
            part = path[idx]
            assert isinstance(
                part, int
            ), f"{part=} should be an int at {pretty_path(path[:idx + 1])} to match array schema at {pretty_path(schema_path_to_here)}"
            if part < 0 or part >= len(subvalue):
                return {"type": "null"}, None
            assert (
                "items" in subschema
            ), f"{subschema=} should have 'items' at {pretty_path(schema_path_to_here)} to extract {pretty_path(path)}"

            subschema = subschema["items"]
            schema_path_to_here.append("items")
            subvalue = subvalue[part]
            idx += 1
            continue

        if part_type == "null":
            return {"type": "null"}, None

        assert (
            False
        ), f"unexpected schema type {part_type!r} at {pretty_path(schema_path_to_here)} to extract {pretty_path(path[:idx + 1])} for full path {pretty_path(path)}"


@dataclass(frozen=True)
class SplitInputPathResultSuccess:
    type: Literal["success"]
    """It is a split; we've verified up to but not including the extracted path"""
    input_path: List[Union[str, int]]
    extracted_path: List[Union[str, int]]
    target_schema: dict
    target_value: Any


@dataclass(frozen=True)
class SplitInputPathResultNotASplit:
    type: Literal["not_a_split"]
    """It is not a split; we've found what its targeting without extraction"""
    target_schema: dict
    target_value: Any


SplitInputPathResult = Union[SplitInputPathResultSuccess, SplitInputPathResultNotASplit]


def split_input_path_and_extract_path(
    schema: dict, value: Any, path: Union[List[Union[str, int]], List[str], List[int]]
) -> SplitInputPathResult:
    """Intended as a simpler interface for value extraction that providing an
    input path and extracted path or just an input path: a single path is
    provided and we discover that its an extraction because it tries to index
    into a string with a custom format.

    This will find out that either the path requires extraction, doesn't require
    extraction, or is bad and can't be fixed with extraction (results in an AssertionError).
    """
    idx = 0
    subschema = schema
    subvalue = value
    schema_path_to_here = []

    while True:
        if idx == len(path):
            return SplitInputPathResultNotASplit(
                type="not_a_split",
                target_schema=subschema,
                target_value=subvalue,
            )

        assert isinstance(
            subschema, dict
        ), f"{subschema=} should be a dict at {pretty_path(schema_path_to_here)} to extract {pretty_path(path)}"

        if subschema.get("nullable", False) is True and subvalue is None:
            return SplitInputPathResultNotASplit(
                type="not_a_split", target_schema={"type": "null"}, target_value=None
            )

        part_type = subschema.get("type")
        if part_type == "object":
            assert isinstance(
                subvalue, dict
            ), f"{subvalue=} should be a dict at {pretty_path(schema_path_to_here)} to extract {pretty_path(path)}"

            if "x-enum-discriminator" in subschema:
                discriminator = subschema["x-enum-discriminator"]
                assert isinstance(
                    discriminator, str
                ), f"string expected at {pretty_path(schema_path_to_here + ['x-enum-discriminator'])} to extract {pretty_path(path)}"
                assert (
                    discriminator in subvalue
                ), f"{discriminator=} not in {subvalue=} at {pretty_path(schema_path_to_here)} to extract {pretty_path(path)}"

                discrim_value = subvalue[discriminator]
                assert isinstance(
                    discrim_value, str
                ), f"string expected at {pretty_path(schema_path_to_here + ['x-enum-discriminator'])} to extract {pretty_path(path)}"

                one_of = subschema["oneOf"]
                assert isinstance(
                    one_of, list
                ), f"list expected at {pretty_path(schema_path_to_here + ['oneOf'])} to extract {pretty_path(path)}"
                for one_of_idx, one_of_schema in enumerate(one_of):
                    assert isinstance(
                        one_of_schema, dict
                    ), f"dict expected at {pretty_path(schema_path_to_here + ['oneOf', one_of_idx])} to extract {pretty_path(path)}"
                    assert (
                        one_of_schema.get("type") == "object"
                    ), f"'object' expected at {pretty_path(schema_path_to_here + ['oneOf', one_of_idx, 'type'])} to extract {pretty_path(path)}"
                    one_of_properties = one_of_schema.get("properties", dict())
                    assert isinstance(
                        one_of_properties, dict
                    ), f"dict expected at {pretty_path(schema_path_to_here + ['oneOf', one_of_idx, 'properties'])} to extract {pretty_path(path)}"
                    assert (
                        discriminator in one_of_properties
                    ), f"{discriminator=} not in {one_of_properties=} at {pretty_path(schema_path_to_here)} to extract {pretty_path(path)}"

                    oneof_discrim = one_of_properties[discriminator]
                    assert isinstance(
                        oneof_discrim, dict
                    ), f"dict expected at {pretty_path(schema_path_to_here + ['oneOf', one_of_idx, 'properties', discriminator])} to extract {pretty_path(path)}"
                    assert (
                        oneof_discrim.get("type") == "string"
                    ), f"string expected at {pretty_path(schema_path_to_here + ['oneOf', one_of_idx, 'properties', discriminator])} to extract {pretty_path(path)}"
                    oneof_discrim_enum = oneof_discrim.get("enum")
                    assert isinstance(
                        oneof_discrim_enum, list
                    ), f"list expected at {pretty_path(schema_path_to_here + ['oneOf', one_of_idx, 'properties', discriminator, 'enum'])} to extract {pretty_path(path)}"
                    if discrim_value in oneof_discrim_enum:
                        continue

                    subschema = one_of_schema
                    schema_path_to_here.extend(["oneOf", one_of_idx])
                    break
                else:
                    assert (
                        False
                    ), f"no oneOf schema matched x-enum-discriminator {discriminator!r} {discrim_value=} at {pretty_path(schema_path_to_here)} to extract {pretty_path(path)}"
                continue

            part = path[idx]
            assert isinstance(
                part, str
            ), f"{part=} should be a string at {pretty_path(path[:idx + 1])} to match object schema at {pretty_path(schema_path_to_here)}"
            props = subschema.get("properties", dict())
            assert isinstance(
                props, dict
            ), f"{props=} at {pretty_path(schema_path_to_here)} to extract {pretty_path(path)}"
            assert (
                part in props
            ), f"{part=} not in {props=} at {pretty_path(schema_path_to_here)} to extract {pretty_path(path)}"
            assert isinstance(
                subvalue, dict
            ), f"{subvalue=} should be a dict at {pretty_path(path[:idx + 1])} to extract {pretty_path(path)}"

            if part not in subvalue:
                required = subschema.get("required", list())
                assert isinstance(
                    required, list
                ), f"{required=} should be a list at {pretty_path(schema_path_to_here)} to extract {pretty_path(path)}"
                if part not in required:
                    return SplitInputPathResultNotASplit(
                        type="not_a_split",
                        target_schema={"type": "null"},
                        target_value=None,
                    )
                assert (
                    False
                ), f"{part=} not in {subvalue=} at {pretty_path(path[:idx + 1])} to extract {pretty_path(path)}, despite required"

            subschema = props[part]
            schema_path_to_here.extend(["properties", part])
            subvalue = subvalue[part]
            idx += 1
            continue

        if part_type == "array":
            assert isinstance(
                subvalue, list
            ), f"{subvalue=} should be a list at {pretty_path(schema_path_to_here)} to extract {pretty_path(path)}"
            part = path[idx]
            assert isinstance(
                part, int
            ), f"{part=} should be an int at {pretty_path(path[:idx + 1])} to match array schema at {pretty_path(schema_path_to_here)}"
            if part < 0 or part >= len(subvalue):
                return SplitInputPathResultNotASplit(
                    type="not_a_split",
                    target_schema={"type": "null"},
                    target_value=None,
                )
            assert (
                "items" in subschema
            ), f"{subschema=} should have 'items' at {pretty_path(schema_path_to_here)} to extract {pretty_path(path)}"

            subschema = subschema["items"]
            schema_path_to_here.append("items")
            subvalue = subvalue[part]
            idx += 1
            continue

        if part_type == "null":
            return SplitInputPathResultNotASplit(
                type="not_a_split", target_schema={"type": "null"}, target_value=None
            )

        if part_type == "string" and subschema.get("format") is not None:
            return SplitInputPathResultSuccess(
                type="success",
                input_path=cast(List[Union[str, int]], path[:idx]),
                extracted_path=cast(List[Union[str, int]], path[idx:]),
                target_schema=subschema,
                target_value=subvalue,
            )

        assert (
            False
        ), f"unexpected schema type {part_type!r} at {pretty_path(schema_path_to_here)} to extract {pretty_path(path[:idx + 1])} for full path {pretty_path(path)}"


@dataclass(frozen=True)
class ExtractFromModelJsonSchemaSuccess:
    type: Literal["success"]
    schema: dict
    schema_path: List[Union[str, int]]
    """Where `schema` can be found within the original schema via deep_extract."""
    is_potentially_missing_or_none: bool
    """True if the schema is potentially missing or None, meaning that it is not required to be present"""


@dataclass(frozen=True)
class ExtractFromModelJsonSchemaFailure:
    type: Literal["failure"]
    failed_path: List[Union[str, SpecialIndex]]
    failure_reason: str


ExtractFromModelJsonSchemaResult = Union[
    ExtractFromModelJsonSchemaSuccess, ExtractFromModelJsonSchemaFailure
]


def extract_from_model_json_schema(
    result: dict,
    path: Union[List[Union[str, SpecialIndex]], List[str], List[SpecialIndex]],
) -> ExtractFromModelJsonSchemaResult:
    """Extracts the subschema at the given path from the result given as if by a pydantic
    model_json_schema call, which produces a dict with key `$defs`, within which are
    a bunch of schemas, and which can reference schemas in the form {"$ref": "#/$defs/SomeSchema"}.

    Nested schemas are forbidden. Remote references are forbidden.

    This uses asserts to handle schemas it doesn't support and a result of failure if the path
    doesn't match a schema it does support.
    """
    defs = result.get("$defs", dict())
    schema_path_to_here: List[Union[str, int]] = []
    path_to_here: List[Union[str, SpecialIndex]] = []
    src = result
    idx = 0
    nullable = False
    while True:
        assert isinstance(
            src, dict
        ), f"{src=} should be a dict at {pretty_path(schema_path_to_here)} to extract {pretty_path(path)}"

        if src.get("nullable", False) is True:
            nullable = True

        if "allOf" in src:
            # pydantic uses allOf with one item to switch to a ref, not sure exactly why
            all_of = src["allOf"]
            assert isinstance(
                all_of, list
            ), f"{all_of=} at {pretty_path(schema_path_to_here)} to extract {pretty_path(path)}"
            assert (
                len(all_of) == 1
            ), f"{all_of=} at {pretty_path(schema_path_to_here)} to extract {pretty_path(path)}"
            src = all_of[0]
            schema_path_to_here.append("allOf")
            continue
        if "$ref" in src:
            ref_path = src["$ref"]
            assert isinstance(
                ref_path, str
            ), f"{ref_path=} at {pretty_path(schema_path_to_here)} to extract {pretty_path(path)}"
            prefix = "#/$defs/"
            assert ref_path.startswith(
                prefix
            ), f"{ref_path=} at {pretty_path(schema_path_to_here)} to extract {pretty_path(path)}"
            ref_name = ref_path[len(prefix) :]
            assert (
                ref_name in defs
            ), f"{ref_name=} at {pretty_path(schema_path_to_here)} to extract {pretty_path(path)}"
            src = defs[ref_name]
            schema_path_to_here.append(f"->$defs[{ref_path}]")
            continue
        if "anyOf" in src:
            # uses anyOf with one null option for nullable fields
            any_of = src["anyOf"]
            assert isinstance(
                any_of, list
            ), f"{any_of=} at {pretty_path(schema_path_to_here)} to extract {pretty_path(path)}"
            assert all(
                isinstance(x, dict) for x in any_of
            ), f"{any_of=} has non-dict item at {pretty_path(schema_path_to_here)} to extract {pretty_path(path)}"
            non_null_schema = [
                cast(Tuple[int, dict], (idx, x))
                for idx, x in enumerate(any_of)
                if x.get("type") != "null"
            ]
            assert (
                len(non_null_schema) == 1
            ), f"{any_of=} not exactly 1 non-null schema at {pretty_path(schema_path_to_here)} to extract {pretty_path(path)}"
            src = non_null_schema[0][1]
            schema_path_to_here.extend(["anyOf", non_null_schema[0][0]])
            if len(non_null_schema) < len(any_of):
                nullable = True
            continue

        if idx == len(path):
            return ExtractFromModelJsonSchemaSuccess(
                type="success",
                schema=src,
                schema_path=schema_path_to_here,
                is_potentially_missing_or_none=nullable,
            )

        part = path[idx]
        src_type = src.get("type")
        if src_type == "object":
            if not isinstance(part, str):
                return ExtractFromModelJsonSchemaFailure(
                    type="failure",
                    failed_path=path_to_here + [part],
                    failure_reason=f"expected string part in path since schema type at {pretty_path(schema_path_to_here)} is 'object'",
                )
            props = src.get("properties", dict())
            assert isinstance(
                props, dict
            ), f"{props=} at {pretty_path(schema_path_to_here)} to extract {pretty_path(path)}"
            if part not in props:
                return ExtractFromModelJsonSchemaFailure(
                    type="failure",
                    failed_path=path_to_here + [part],
                    failure_reason=f"expected {part} in properties at {pretty_path(schema_path_to_here)} to extract {pretty_path(path)}",
                )
            src = props[part]
            schema_path_to_here.extend(["properties", part])
            path_to_here.append(part)
            idx += 1
            continue

        if src_type == "array":
            if part != SpecialIndex.ARRAY_INDEX:
                return ExtractFromModelJsonSchemaFailure(
                    type="failure",
                    failed_path=path_to_here + [part],
                    failure_reason=f"expected array index at {pretty_path(schema_path_to_here)} to extract {pretty_path(path)}",
                )
            assert (
                "items" in src
            ), f"{src=} at {pretty_path(schema_path_to_here)} to extract {pretty_path(path)}"
            src = src["items"]
            schema_path_to_here.append("items")
            nullable = True
            path_to_here.append(SpecialIndex.ARRAY_INDEX)
            idx += 1
            continue

        return ExtractFromModelJsonSchemaFailure(
            type="failure",
            failed_path=path_to_here + [part],
            failure_reason=f"expected 'object' or 'array' at {pretty_path(schema_path_to_here)}, got {src_type!r} to extract {pretty_path(path)}",
        )


def deep_extract(
    original: Union[dict, list],
    path: Union[List[Union[str, int]], List[str], List[int]],
) -> Any:
    src = original
    for idx, item in enumerate(path):
        if isinstance(item, str):
            if not isinstance(src, dict):
                raise KeyError(
                    f"Expected dict in src at {pretty_path(path[:idx + 1])} to extract {pretty_path(path)}, got {src}"
                )
            src = src[item]
        else:
            if not isinstance(src, list):
                raise KeyError(
                    f"Expected list in src at {pretty_path(path[:idx + 1])} to extract {pretty_path(path)}, got {src}"
                )
            src = src[item]
    return src


@dataclass
class ExtractSchemaDefaultValueSuccess:
    type: Literal["success"]
    """indicates that the extraction was successful"""
    value: Any


@dataclass
class ExtractSchemaDefaultValueIrrelevant:
    type: Literal["irrelevant"]
    """indicates that the extraction failed because if you walk to that
    path you find a nullable field set to null
    """


def extract_schema_default_value(
    *,
    schema: dict,
    fixed: dict,
    path: Union[List[Union[str, int]], List[str], List[int]],
) -> Union[ExtractSchemaDefaultValueSuccess, ExtractSchemaDefaultValueIrrelevant]:
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
    src = cast(Optional[dict], fixed)
    src_schema = schema
    src_schema_path = []
    src_path = []

    idx = 0
    while idx < len(path):
        item = path[idx]

        if src is None:
            if "default" not in src_schema:
                raise KeyError(
                    f"Expected default in schema at {pretty_path(src_schema_path)} to extract {pretty_path(path)}"
                )
            src = src_schema["default"]
            src_path = src_schema_path + ["default"]

            if src is None:
                if src_schema.get("nullable", False) is not True:
                    raise KeyError(
                        f"Expected default is not None or nullable is True at {pretty_path(src_schema_path)} to extract {pretty_path(path)}"
                    )
                return ExtractSchemaDefaultValueIrrelevant(type="irrelevant")

        if src_schema.get("type") == "array":
            if not isinstance(item, int):
                raise KeyError(
                    f"Expected int in path at {pretty_path(src_schema_path)} to extract {pretty_path(path)}, got {item}"
                )

            if "items" not in src_schema:
                raise KeyError(
                    f"Expected items in schema at {pretty_path(src_schema_path)} to extract {pretty_path(path)}"
                )

            if src is not None:
                if not isinstance(src, list):
                    raise KeyError(
                        f"Expected list in src at {pretty_path(src_schema_path)} to extract {pretty_path(path)}, got {src}"
                    )

                if item < 0 or item >= len(src):
                    raise KeyError(
                        f"Expected {item} in range in src at {pretty_path(src_schema_path)} to extract {pretty_path(path)}, got {src}"
                    )

            src_schema = src_schema["items"]
            src_schema_path = src_schema_path + ["items"]
            if src is not None:
                src = src[item]
                src_path.append(item)
            idx += 1
            continue

        if src_schema.get("type") != "object":
            raise KeyError(
                f"Expected object in schema at {pretty_path(src_schema_path)} to extract {pretty_path(path)}, got {src_schema}"
            )

        if not isinstance(item, str):
            raise KeyError(
                f"Expected str in path at {pretty_path(src_schema_path)} to extract {pretty_path(path)}, got {item}"
            )

        if "properties" not in src_schema:
            if "oneOf" in src_schema and "x-enum-discriminator" in src_schema:
                discriminator = src_schema["x-enum-discriminator"]
                assert isinstance(
                    discriminator, str
                ), f"{discriminator=} at {pretty_path(path[:idx + 1])} to extract {pretty_path(path)}"

                if discriminator not in src:
                    raise KeyError(
                        f"Expected discriminator {discriminator} in {src} from {pretty_path(src_path)} to extract {pretty_path(path)}"
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

                continue
            else:
                raise KeyError(
                    f"Expected properties in schema at {pretty_path(src_schema_path)} to extract {pretty_path(path)}"
                )

        if item not in src_schema["properties"]:
            raise KeyError(
                f"Expected standard property {item} in {src_schema['properties']} at {pretty_path(src_schema_path)} to extract {pretty_path(path)}"
            )

        src_schema = src_schema["properties"][item]
        src_schema_path = src_schema_path + ["properties", item]

        if src is None or item not in src:
            if "default" not in src_schema:
                raise KeyError(
                    f"Expected default in schema at {pretty_path(src_schema_path)} to extract {pretty_path(path)}"
                )
            src = src_schema["default"]
            src_path = src_schema_path + ["default"]
        else:
            src = src[item]
            src_path.append(item)

        idx += 1

    return ExtractSchemaDefaultValueSuccess(type="success", value=src)


def deep_set(
    original: Union[dict, list],
    path: Union[List[Union[str, int]], List[str], List[int]],
    value: Any,
    auto_extend_lists: bool = False,
) -> None:
    assert path, f"_deep_set empty path on {original}, value {value}, path {path}"
    src = original
    for item_idx, item in enumerate(path[:-1]):
        if isinstance(item, str):
            assert isinstance(
                src, dict
            ), f"Expected dict in src at {pretty_path(path)} to set {value}, got {src}"
            nxt = src.get(item)
            if nxt is None:
                nxt = dict()
                src[item] = nxt
            src = nxt
        elif isinstance(item, int):
            assert isinstance(
                src, list
            ), f"Expected list in src at {pretty_path(path)} to set {value}, got {src}"
            if item < 0 or item > len(src):
                raise IndexError(
                    f"Expected {item} in range in src at {pretty_path(path)} to set {value}, got {src}"
                )
            if item == len(src):
                if not auto_extend_lists:
                    raise IndexError(
                        f"Expected {item} in range in src at {pretty_path(path)} to set {value}, got {src} (did we want auto_extend=True?)"
                    )
                next_item = path[item_idx + 1]
                if isinstance(next_item, int):
                    src.append([])
                else:
                    src.append(dict())
            src = src[item]
        else:
            raise ValueError(f"Expected str or int in path, got {item!r}")

    last_key = path[-1]
    if isinstance(last_key, str):
        assert isinstance(
            src, dict
        ), f"Expected dict in src at {pretty_path(path)} to set {value}, got {src}"
        src[last_key] = value
    elif isinstance(last_key, int):
        assert isinstance(
            src, list
        ), f"Expected list in src at {pretty_path(path)} to set {value}, got {src}"
        if last_key < 0 or last_key > len(src):
            raise IndexError(
                f"Expected {last_key} in range in src at {pretty_path(path)} to set {value}, got {src}"
            )
        if last_key == len(src):
            if not auto_extend_lists:
                raise IndexError(
                    f"Expected {last_key} in range in src at {pretty_path(path)} to set {value}, got {src} (did we want auto_extend=True?)"
                )
            src.append(value)
        else:
            src[last_key] = value
    else:
        raise ValueError(f"Expected str or int in path, got {last_key!r}")


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
