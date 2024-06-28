from dataclasses import dataclass
import os
import string
from typing import Any, Dict, List, Literal, Set, Type, Union, cast

import aiohttp
from jsonschema import Validator
from openapi_schema_validator import OAS30Validator, validate

from itgs import Itgs
from lib.client_flows.helper import (
    check_oas_30_schema,
    deep_copy,
    deep_set,
    pretty_path,
)
from lib.client_flows.special_index import SpecialIndex
from touch_points.lib.schema.walk_schema import SchemaVisitor, walk_schema
from touch_points.lib.touch_points import (
    TouchPointMessages,
    TouchPointTemplateParameterSubstitution,
)


@dataclass
class TouchPointSchemaResultSuccess:
    success: Literal[True]
    """
    - `True`: the schema is reasonable, and the messages are sensible for the
      given event schema.
    """


@dataclass
class TouchPointSchemaResultError:
    success: Literal[False]
    """
    - `False`: the schema is not acceptable or its unlikely that the trigger will
      succeed with the given messages and schema (for example, messages depends on
      a parameter which is not required in the schema)
    """
    category: Literal["schema", "messages"]
    """
    - `schema`: the issue is in the schema itself, and would occur regardless of the
      choice of messages
    - `messages`: the schema might be alright, but the pairing of schema and messages
      is not likely to result in a successful trigger
    """
    message: str
    """
    Describes in plain text what the issue is. For sensible formatting this
    depends on line wrapping, singular newlines being respected, and two or more
    newlines in a row collapsed into a paragraph break. It does not depend on
    leading or trailing whitespace, including within lines or paragraphs, being
    preserved.
    """


TouchPointSchemaResult = Union[
    TouchPointSchemaResultSuccess, TouchPointSchemaResultError
]


async def check_touch_point_schema(
    itgs: Itgs,
    /,
    *,
    schema: dict,
    messages: TouchPointMessages,
) -> TouchPointSchemaResult:
    """Determines if the given touch point event schema is valid, and that the
    messages would likely to be formattable given event parameters meeting the
    event schema.

    This is more strict than saying there exists an object that meets the schema
    and can be formatted with the messages. This is less strict than saying all
    objects that meet the schema can be formatted with the messages. The former
    would mean a schema of `{}` would always pass, whereas the latter would mean
    a lot of time spent restricting the schema to avoid edge cases. The middle
    ground is selected as what results in the most useful error messages in admin:
    too loose and basic human errors aren't found until trigger time, too strict
    and writing a valid schema becomes a chore.
    """
    try:
        check_oas_30_schema(schema, require_example=True)
    except Exception as e:
        return TouchPointSchemaResultError(
            success=False,
            category="schema",
            message=str(e),
        )

    for idx, message in enumerate(messages.sms):
        for parameter in message.body_parameters:
            try:
                check_parameter(schema, parameter)
            except Exception as e:
                return TouchPointSchemaResultError(
                    success=False,
                    category="messages",
                    message=f"sms[{idx}] body parameter `{parameter}`: {str(e)}",
                )
        try:
            check_format_uses_parameters(message.body_format, message.body_parameters)
        except Exception as e:
            return TouchPointSchemaResultError(
                success=False,
                category="messages",
                message=f"sms[{idx}] body format: {str(e)}",
            )

    for idx, message in enumerate(messages.push):
        for parameter in message.body_parameters:
            try:
                check_parameter(schema, parameter)
            except Exception as e:
                return TouchPointSchemaResultError(
                    success=False,
                    category="messages",
                    message=f"push[{idx}] body parameter `{parameter}`: {str(e)}",
                )
        try:
            check_format_uses_parameters(message.body_format, message.body_parameters)
        except Exception as e:
            return TouchPointSchemaResultError(
                success=False,
                category="messages",
                message=f"push[{idx}] body format: {str(e)}",
            )

        for parameter in message.title_parameters:
            try:
                check_parameter(schema, parameter)
            except Exception as e:
                return TouchPointSchemaResultError(
                    success=False,
                    category="messages",
                    message=f"push[{idx}] title parameter `{parameter}`: {str(e)}",
                )

        try:
            check_format_uses_parameters(message.title_format, message.title_parameters)
        except Exception as e:
            return TouchPointSchemaResultError(
                success=False,
                category="messages",
                message=f"push[{idx}] title format: {str(e)}",
            )

    for idx, message in enumerate(messages.email):
        for parameter in message.subject_parameters:
            try:
                check_parameter(schema, parameter)
            except Exception as e:
                return TouchPointSchemaResultError(
                    success=False,
                    category="messages",
                    message=f"email[{idx}] body parameter `{parameter}`: {str(e)}",
                )

        try:
            check_format_uses_parameters(
                message.subject_format, message.subject_parameters
            )
        except Exception as e:
            return TouchPointSchemaResultError(
                success=False,
                category="messages",
                message=f"email[{idx}] body format: {str(e)}",
            )

        for substituted in message.template_parameters_substituted:
            for parameter in substituted.parameters:
                try:
                    check_parameter(schema, parameter)
                except Exception as e:
                    return TouchPointSchemaResultError(
                        success=False,
                        category="messages",
                        message=f"email[{idx}] substitution for {pretty_path(substituted.key)} parameter `{parameter}`: {str(e)}",
                    )

            try:
                check_format_uses_parameters(substituted.format, substituted.parameters)
            except Exception as e:
                return TouchPointSchemaResultError(
                    success=False,
                    category="messages",
                    message=f"email[{idx}] substitution for {pretty_path(substituted.key)} format: {str(e)}",
                )

    if not messages.email:
        return TouchPointSchemaResultSuccess(success=True)

    email_templates_schema = await get_email_template_schema()

    ctx_by_template: Dict[str, CompileContext] = dict()

    for idx, message in enumerate(messages.email):
        email_template_schema = email_templates_schema.get(message.template)
        if email_template_schema is None:
            return TouchPointSchemaResultError(
                success=False,
                category="messages",
                message=f"email[{idx}] template {message.template} not found in email-templates",
            )

        ctx = ctx_by_template.get(message.template)
        if ctx is None:
            compiler = InitCompileContext()
            walk_schema(email_template_schema, compiler)
            ctx = compiler.finish()
            ctx_by_template[message.template] = ctx

        ctx = ctx.clone_like_initialized()

        for key, value in message.template_parameters_fixed.items():
            try:
                check_fixed_email_parameter(
                    email_template_schema,
                    key=key.split("."),
                    value=value,
                    ctx=ctx,
                )
            except Exception as e:
                return TouchPointSchemaResultError(
                    success=False,
                    category="messages",
                    message=f"email[{idx}] fixed parameter {pretty_path(key.split('.'))}: {str(e)}",
                )

        for substituted in message.template_parameters_substituted:
            try:
                check_substituted_email_parameter(
                    email_template_schema,
                    key=substituted.key,
                    ctx=ctx,
                )
            except Exception as e:
                return TouchPointSchemaResultError(
                    success=False,
                    category="messages",
                    message=f"email[{idx}] substitution for {pretty_path(substituted.key)}: {str(e)}",
                )

        try:
            check_example_event_matches_email_schema(
                schema,
                message.template_parameters_fixed,
                message.template_parameters_substituted,
                email_template_schema,
            )
        except Exception as e:
            return TouchPointSchemaResultError(
                success=False,
                category="messages",
                message=f"email[{idx}] example event: {str(e)}",
            )

    return TouchPointSchemaResultSuccess(success=True)


async def get_email_template_schema() -> Dict[str, dict]:
    """Gets the email templates schemas by template slug"""
    root_email_template_url = os.environ["ROOT_EMAIL_TEMPLATE_URL"]
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{root_email_template_url}/api/3/openapi.json", allow_redirects=False
        ) as response:
            response.raise_for_status()
            email_template_schema = await response.json()

    by_slug = dict()
    for path, path_item_raw in cast(
        Dict[str, dict], email_template_schema["paths"]
    ).items():
        if not path.startswith("/api/3/templates/"):
            continue
        if "$ref" in path_item_raw:
            continue
        post = path_item_raw.get("post")
        if post is None:
            continue
        tags = post.get("tags")
        if tags is None or not isinstance(tags, list) or "templates" not in tags:
            continue

        slug = path[len("/api/3/templates/") :]
        request_body = post.get("requestBody")
        if not isinstance(request_body, dict):
            continue
        if "$ref" in request_body:
            continue

        content = request_body.get("content")
        if not isinstance(content, dict):
            continue

        json_body = content["application/json; charset=utf-8"]
        if not isinstance(json_body, dict):
            continue

        schema = json_body.get("schema")
        if not isinstance(schema, dict):
            continue

        try:
            OAS30Validator.check_schema(schema)
        except Exception as e:
            raise ValueError(f"invalid schema for email template {slug}: {str(e)}")

        by_slug[slug] = schema
    return by_slug


@dataclass
class EnumDiscriminatorInfo:
    remaining: Set[str]
    """The remaining still possible values"""

    eliminated: Dict[str, str]
    """Maps from discriminator values we've eliminated to one of the errors that eliminated that value
    """

    def clone_like_initialized(self):
        remaining = self.remaining.copy()
        remaining.update(self.eliminated.keys())
        return EnumDiscriminatorInfo(remaining, dict())


@dataclass
class CompileContext:
    remaining_by_pretty_path: Dict[str, EnumDiscriminatorInfo]
    """The key is a pretty_path to the enum discriminator,
    for example, if the email has "footer" which is an object
    with x-enum-discriminator "type", then the set would be
    "$.footer.type", and the
    """

    def clone_like_initialized(self):
        return CompileContext(
            {
                k: v.clone_like_initialized()
                for k, v in self.remaining_by_pretty_path.items()
            }
        )


@dataclass
class CheckParameterStackItem:
    key_to_here: List[str]
    schema_path_to_here: List[Union[str, int]]
    key_from_here: List[str]
    schema: Any


def check_parameter(schema: dict, parameter: str) -> None:
    """Verifies that the given parameter is actually within the schema and makes
    sense to reference directly.

    Since the schema describes the incoming values, the parameter must make sense
    regardless of which `oneOf` branch is taken.
    """
    key = parameter.split(".")

    stack: List[CheckParameterStackItem] = [
        CheckParameterStackItem(
            key_to_here=[],
            schema_path_to_here=[],
            key_from_here=list(key),
            schema=schema,
        )
    ]
    errors: List[str] = []

    while stack:
        item = stack.pop()
        if not isinstance(item.schema, dict):
            errors.append(
                f"expected object at {pretty_path(item.schema_path_to_here)}, got {type(item.schema)}"
            )
            continue

        typ = item.schema.get("type")

        if len(item.key_from_here) == 0:
            if typ not in ["string", "number"]:
                errors.append(
                    f"in leaf object at {pretty_path(item.schema_path_to_here)}, expected 'type' key is a string or number, got {typ}"
                )
            continue

        if typ != "object":
            errors.append(
                f"in order to retrieve {item.key_from_here[0]} from {pretty_path(item.schema_path_to_here)}, expected 'type' key is 'object', got {typ}"
            )
            continue

        prev_len = len(stack)

        if "properties" in item.schema:
            properties = item.schema["properties"]
            if not isinstance(properties, dict):
                errors.append(
                    f"expected {pretty_path(item.schema_path_to_here + ['properties'])} to be an object, got {type(properties)}"
                )
            else:
                stack.append(
                    CheckParameterStackItem(
                        key_to_here=item.key_to_here + item.key_from_here[:1],
                        schema_path_to_here=item.schema_path_to_here
                        + ["properties", item.key_from_here[0]],
                        key_from_here=item.key_from_here[1:],
                        schema=properties.get(item.key_from_here[0]),
                    )
                )

        if "oneOf" in item.schema:
            for idx, one_of in enumerate(item.schema["oneOf"]):
                stack.append(
                    CheckParameterStackItem(
                        key_to_here=item.key_to_here,
                        schema_path_to_here=item.schema_path_to_here + ["oneOf", idx],
                        key_from_here=item.key_from_here,
                        schema=one_of,
                    )
                )

        if "allOf" in item.schema:
            for idx, all_of in enumerate(item.schema["allOf"]):
                stack.append(
                    CheckParameterStackItem(
                        key_to_here=item.key_to_here,
                        schema_path_to_here=item.schema_path_to_here + ["allOf", idx],
                        key_from_here=item.key_from_here,
                        schema=all_of,
                    )
                )

        if prev_len == len(stack):
            errors.append(
                f"expected {pretty_path(item.schema_path_to_here)} to have 'properties', 'oneOf', or 'allOf' key for nesting"
            )
            continue

    if errors:
        raise ValueError("\n".join(errors))


def check_format_uses_parameters(format: str, parameters: List[str]) -> None:
    """Checks that the given format string uses all the given parameters, and
    only those parameters
    """
    fmt = string.Formatter()
    remaining = set(parameters)
    for literal_text, field_name, format_spec, conversion in fmt.parse(format):
        if field_name is None:
            continue
        field_name_dot = python_format_to_dot_format(field_name)
        if field_name_dot not in parameters:
            raise ValueError(f"unknown parameter {field_name_dot} in format string")
        remaining.remove(field_name_dot)

    if remaining:
        raise ValueError(f"requested parameters {remaining} not used in format string")


def python_format_to_dot_format(python_format: str) -> str:
    """Converts a python format string to a dot format string"""
    return python_format.replace("[", ".").replace("]", "")


@dataclass
class CheckEmailParameterStackItem:
    key_to_here: List[Union[str, int]]
    schema_path_to_here: List[Union[str, int]]
    key_from_here: List[Union[str, int]]
    schema: Any
    discriminators_to_here: Dict[str, str]


def check_fixed_email_parameter(
    email_template_schema: dict,
    /,
    *,
    key: Union[List[Union[str, int]], List[str], List[int]],
    value: Any,
    ctx: CompileContext,
) -> None:
    """Checks that the given value can be assigned to the given key, using the
    template schema.

    Since the schema represents the value we're targeting, the key only
    needs to make sense for at least 1 of the `oneOf` branches. We use the
    ctx to indicate which ones we've eliminated
    """
    # we only check leaf nodes, as substitutions could make other nodes viable later
    if isinstance(value, list):
        for idx, item in enumerate(value):
            check_fixed_email_parameter(
                email_template_schema,
                key=key + [idx],
                value=item,
                ctx=ctx,
            )
        return

    if isinstance(value, dict):
        for k, v in value.items():
            check_fixed_email_parameter(
                email_template_schema,
                key=key + [k],
                value=v,
                ctx=ctx,
            )
        return

    stack: List[CheckEmailParameterStackItem] = [
        CheckEmailParameterStackItem(
            key_to_here=[],
            schema_path_to_here=[],
            key_from_here=list(key),
            schema=email_template_schema,
            discriminators_to_here=dict(),
        )
    ]
    errors: List[str] = []

    def on_errored(itm: CheckEmailParameterStackItem, msg: str):
        errors.append(msg)
        for (
            discriminator_path,
            discriminator_value,
        ) in itm.discriminators_to_here.items():
            discriminator_info = ctx.remaining_by_pretty_path[discriminator_path]
            if discriminator_value in discriminator_info.remaining:
                discriminator_info.remaining.remove(discriminator_value)
                discriminator_info.eliminated[discriminator_value] = msg

    found_working_path = False
    while stack:
        item = stack.pop()
        if not isinstance(item.schema, dict):
            on_errored(
                item,
                f"expected object at {pretty_path(item.schema_path_to_here)}, got {type(item.schema)}",
            )
            continue

        if len(item.key_from_here) == 0:
            validator = OAS30Validator(item.schema)
            try:
                validator.validate(value)
                found_working_path = True
            except Exception as e:
                on_errored(
                    item,
                    f"invalid value for {pretty_path(item.schema_path_to_here)}: {str(e)}",
                )
            continue

        typ = item.schema.get("type")
        if typ == "array":
            if not isinstance(item.key_from_here[0], int):
                on_errored(
                    item,
                    f"{pretty_path(item.schema_path_to_here)} is an array, so require integer key at {item.key_from_here[0]}",
                )
                continue

            items = item.schema.get("items")
            if not isinstance(items, dict):
                on_errored(
                    item,
                    f"expected object at {pretty_path(item.schema_path_to_here + ['items'])}, got {type(items)}",
                )
                continue
            stack.append(
                CheckEmailParameterStackItem(
                    key_to_here=item.key_to_here + item.key_from_here[:1],
                    schema_path_to_here=item.schema_path_to_here + ["items"],
                    key_from_here=item.key_from_here[1:],
                    schema=items,
                    discriminators_to_here=item.discriminators_to_here,
                )
            )
            continue

        if typ != "object":
            on_errored(
                item,
                f"in order to retrieve {item.key_from_here[0]} from {pretty_path(item.schema_path_to_here)}, expected 'type' key is 'object', got {typ}",
            )
            continue

        one_of = item.schema.get("oneOf")
        if one_of is not None and not isinstance(one_of, list):
            on_errored(
                item,
                f"expected list or None at {pretty_path(item.schema_path_to_here + ['oneOf'])}, got {type(one_of)}",
            )
            continue

        if isinstance(one_of, list):
            discriminator = item.schema.get("x-enum-discriminator")
            if not isinstance(discriminator, str):
                on_errored(
                    item,
                    f"expected string at {pretty_path(item.schema_path_to_here + ['x-enum-discriminator'])}, got {type(discriminator)}",
                )
                continue

            discriminator_key = pretty_path(item.key_to_here + [discriminator])
            if discriminator_key in item.discriminators_to_here:
                on_errored(
                    item,
                    f"already used {discriminator_key} in this path",
                )
                continue

            discriminator_info = ctx.remaining_by_pretty_path.get(discriminator_key)

            if discriminator_info is None:
                generic_key = [
                    SpecialIndex.ARRAY_INDEX if isinstance(k, int) else k
                    for k in item.key_to_here
                ] + [discriminator]
                generic_info = ctx.remaining_by_pretty_path.get(
                    pretty_path(generic_key)
                )
                if generic_info is None:
                    on_errored(
                        item,
                        f"did not find {discriminator_key} as x-enum-discriminator during compilation step "
                        f"(checked generic key: {pretty_path(generic_key)})."
                        f"did find: {ctx.remaining_by_pretty_path.keys()}",
                    )
                    continue

                discriminator_info = generic_info.clone_like_initialized()
                ctx.remaining_by_pretty_path[discriminator_key] = discriminator_info

            if not discriminator_info.remaining:
                on_errored(
                    item, f"no remaining values for {discriminator_key} possible"
                )
                continue

            found_viable_one_of = False
            for one_of_idx, one_of_item in enumerate(one_of):
                one_of_path = item.schema_path_to_here + ["oneOf", one_of_idx]
                if not isinstance(one_of_item, dict):
                    on_errored(
                        item,
                        f"expected object at {pretty_path(one_of_path)}, got {type(one_of_item)}",
                    )
                    continue

                one_of_properties = one_of_item.get("properties")
                if not isinstance(one_of_properties, dict):
                    on_errored(
                        item,
                        f"expected object at {pretty_path(one_of_path + ['properties'])}, got {type(one_of_properties)}",
                    )
                    continue

                one_of_discriminator = one_of_properties.get(discriminator)
                one_of_discrim_schema_path = one_of_path + ["properties", discriminator]
                if not isinstance(one_of_discriminator, dict):
                    on_errored(
                        item,
                        f"expected object at {pretty_path(one_of_discrim_schema_path)}, got {type(one_of_discriminator)}",
                    )
                    continue

                one_of_discrim_type = one_of_discriminator.get("type")
                if one_of_discrim_type != "string":
                    on_errored(
                        item,
                        f"expected 'string' at {pretty_path(one_of_discrim_schema_path + ['type'])}, got {one_of_discrim_type}",
                    )
                    continue

                one_of_discrim_enum = one_of_discriminator.get("enum")
                if not isinstance(one_of_discrim_enum, list):
                    on_errored(
                        item,
                        f"expected list at {pretty_path(one_of_discrim_schema_path + ['enum'])}, got {type(one_of_discrim_enum)}",
                    )
                    continue

                if len(one_of_discrim_enum) != 1:
                    on_errored(
                        item,
                        f"expected exactly 1 value at {pretty_path(one_of_discrim_schema_path + ['enum'])}, got {len(one_of_discrim_enum)}",
                    )
                    continue

                one_of_discrim_value = one_of_discrim_enum[0]
                if one_of_discrim_value in discriminator_info.remaining:
                    found_viable_one_of = True
                    stack.append(
                        CheckEmailParameterStackItem(
                            key_to_here=item.key_to_here,
                            schema_path_to_here=one_of_path,
                            key_from_here=item.key_from_here,
                            schema=one_of_item,
                            discriminators_to_here={
                                **item.discriminators_to_here,
                                **{discriminator_key: one_of_discrim_value},
                            },
                        )
                    )

            if not found_viable_one_of:
                on_errored(
                    item,
                    f"no viable oneOf branch found for {discriminator_key}",
                )
                continue

        all_of = item.schema.get("allOf")
        if all_of is not None and not isinstance(all_of, list):
            raise ValueError(
                f"expected list or None at {pretty_path(item.schema_path_to_here + ['allOf'])}, got {type(all_of)}"
            )
        if isinstance(all_of, list):
            raise ValueError(
                f"not supported: {pretty_path(item.schema_path_to_here + ['allOf'])}"
            )

        any_of = item.schema.get("anyOf")
        if any_of is not None and not isinstance(any_of, list):
            raise ValueError(
                f"expected list or None at {pretty_path(item.schema_path_to_here + ['anyOf'])}, got {type(any_of)}"
            )
        if isinstance(any_of, list):
            raise ValueError(
                f"not supported: {pretty_path(item.schema_path_to_here + ['anyOf'])}"
            )

        not_ = item.schema.get("not")
        if not_ is not None and not isinstance(not_, dict):
            raise ValueError(
                f"expected object or None at {pretty_path(item.schema_path_to_here + ['not'])}, got {type(not_)}"
            )

        if isinstance(not_, dict):
            raise ValueError(
                f"not supported: {pretty_path(item.schema_path_to_here + ['not'])}"
            )

        properties = item.schema.get("properties")
        if properties is not None and not isinstance(properties, dict):
            raise ValueError(
                f"expected object or None at {pretty_path(item.schema_path_to_here + ['properties'])}, got {type(properties)}"
            )

        if properties is not None and one_of is not None:
            raise ValueError(
                f"not supported: {pretty_path(item.schema_path_to_here)} (only one of one_of, properties supported)"
            )

        if isinstance(properties, dict):
            if item.key_from_here[0] not in properties:
                on_errored(
                    item,
                    f"expected {item.key_from_here[0]} in {pretty_path(item.schema_path_to_here + ['properties'])}",
                )
                continue

            stack.append(
                CheckEmailParameterStackItem(
                    key_to_here=item.key_to_here + item.key_from_here[:1],
                    schema_path_to_here=item.schema_path_to_here
                    + ["properties", item.key_from_here[0]],
                    key_from_here=item.key_from_here[1:],
                    schema=properties.get(item.key_from_here[0]),
                    discriminators_to_here=item.discriminators_to_here,
                )
            )

    if not found_working_path:
        raise ValueError("\n".join(errors))


def check_substituted_email_parameter(
    email_template_schema: dict,
    /,
    *,
    key: Union[List[Union[str, int]], List[str], List[int]],
    ctx: CompileContext,
) -> None:
    """Checks that a dynamic string value can be stored in the given key, using the
    template schema.

    Since the schema represents the value we're targeting, the key only
    needs to make sense for at least 1 of the `oneOf` branches. We use the
    ctx to indicate which ones we've eliminated
    """
    check_fixed_email_parameter(
        email_template_schema,
        key=key,
        value="some-dynamic-value",
        ctx=ctx,
    )


def check_example_event_matches_email_schema(
    event_schema: dict,
    template_parameters_fixed: Dict[str, Any],
    template_parameters_substituted: List[TouchPointTemplateParameterSubstitution],
    email_template_schema: dict,
) -> None:
    """Checks that the 'example' on the event schema can be used with the fixed and
    substituted parameters to generate an object which matches the email template
    schema.
    """
    event_parameters = event_schema["example"]
    if not isinstance(event_parameters, dict):
        raise ValueError(f"expected object at $.example, got {type(event_parameters)}")

    result = deep_copy(template_parameters_fixed)
    for substituted in template_parameters_substituted:
        deep_set(
            result,
            substituted.key,
            format_with_dot_parameters(
                substituted.format,
                parameters=substituted.parameters,
                event_parameters=event_parameters,
            ),
            auto_extend_lists=True,
        )

    validate(result, email_template_schema, cls=cast(Type[Validator], OAS30Validator))


def format_with_dot_parameters(
    format_string: str,
    /,
    *,
    parameters: List[str],
    event_parameters: Dict[str, Any],
) -> str:
    if all("." not in p for p in parameters):
        return format_string.format_map(
            dict((k, event_parameters[k]) for k in parameters)
        )

    result = dict()
    for raw_key in parameters:
        key = raw_key.split(".")
        if len(key) == 1:
            assert key[0] not in result or result[key[0]] == event_parameters[key[0]]
            result[key[0]] = event_parameters[key[0]]
            continue

        current = dict()
        value = event_parameters[key[0]]
        assert isinstance(value, dict)
        result[key[0]] = current

        for idx in range(1, len(key) - 1):
            nxt = current.get(key[idx])
            if nxt is None:
                nxt = dict()
                current[key[idx]] = nxt
            else:
                assert isinstance(nxt, dict)

            current = nxt
            value = value[key[idx]]
            assert isinstance(value, dict)

        current[key[-1]] = value[key[-1]]

    return format_string.format_map(result)


class InitCompileContext(SchemaVisitor):
    def __init__(self):
        self.enum_discriminators: Dict[str, Set[str]] = dict()
        """The enum discriminators we've found so far"""

    def finish(self) -> CompileContext:
        return CompileContext(
            remaining_by_pretty_path=dict(
                (key, EnumDiscriminatorInfo(values, dict()))
                for key, values in self.enum_discriminators.items()
            )
        )

    def on_item(
        self,
        item: dict,
        /,
        *,
        schema_path_from_root: List[Union[str, int]],
        value_path_from_root: List[Union[str, SpecialIndex]],
        inverted: bool,
    ) -> None:
        if inverted:
            return

        if item.get("type") != "object":
            return

        discriminator = item.get("x-enum-discriminator")
        if discriminator is None:
            return

        if not isinstance(discriminator, str):
            raise ValueError(
                f"expected x-enum-discriminator to be a string, got {type(discriminator)} at {pretty_path(schema_path_from_root)}"
            )

        discriminator_path = pretty_path(value_path_from_root + [discriminator])
        if discriminator_path not in self.enum_discriminators:
            self.enum_discriminators[discriminator_path] = set()

        one_of = item.get("oneOf")
        if not isinstance(one_of, list):
            raise ValueError(
                f"expected list at {pretty_path(schema_path_from_root + ['oneOf'])}, got {type(one_of)}"
            )

        for idx, one_of_item in enumerate(one_of):
            if not isinstance(one_of_item, dict):
                raise ValueError(
                    f"expected object at {pretty_path(schema_path_from_root + ['oneOf', idx])}, got {type(one_of_item)}"
                )

            one_of_type = one_of_item.get("type")
            if one_of_type != "object":
                raise ValueError(
                    f"expected 'object' at {pretty_path(schema_path_from_root + ['oneOf', idx, 'type'])}, got {one_of_type}"
                )

            one_of_props = one_of_item.get("properties")
            if not isinstance(one_of_props, dict):
                raise ValueError(
                    f"expected object at {pretty_path(schema_path_from_root + ['oneOf', idx, 'properties'])}, got {type(one_of_props)}"
                )

            one_of_discrim = one_of_props.get(discriminator)
            if not isinstance(one_of_discrim, dict):
                raise ValueError(
                    f"expected object at {pretty_path(schema_path_from_root + ['oneOf', idx, 'properties', discriminator])}, got {type(one_of_discrim)}"
                )

            one_of_discrim_type = one_of_discrim.get("type")
            if one_of_discrim_type != "string":
                raise ValueError(
                    f"expected 'string' at {pretty_path(schema_path_from_root + ['oneOf', idx, 'properties', discriminator, 'type'])}, got {one_of_discrim_type}"
                )

            one_of_enum = one_of_discrim.get("enum")
            if not isinstance(one_of_enum, list):
                raise ValueError(
                    f"expected list at {pretty_path(schema_path_from_root + ['oneOf', idx, 'properties', discriminator, 'enum'])}, got {type(one_of_enum)}"
                )

            for one_of_enum_idx, one_of_enum_val in enumerate(one_of_enum):
                if not isinstance(one_of_enum_val, str):
                    raise ValueError(
                        f"expected string at {pretty_path(schema_path_from_root + ['oneOf', idx, 'properties', discriminator, 'enum', one_of_enum_idx])}, got {type(one_of_enum_val)}"
                    )

                self.enum_discriminators[discriminator_path].add(one_of_enum_val)
