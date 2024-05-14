from dataclasses import dataclass
from functools import partial
import io
import json
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
import jsonschema.exceptions
from jsonschema.protocols import Validator
from typing import (
    Annotated,
    Any,
    Dict,
    List,
    Optional,
    Literal,
    cast,
)
from auth import auth_admin
from rqdb.result import ResultItem
from client_flows.lib.db import (
    STANDARD_CLIENT_FLOW_READ_QUERY,
    parse_client_flow_read_row,
)
from client_flows.lib.parse_flow_screens import (
    decode_flow_screens,
    encode_flow_screens,
    etag_flow_screens,
)
from client_flows.routes.read import ClientFlow
from error_middleware import handle_warning
from itgs import Itgs
from lib.client_flows.client_flow_screen import ClientFlowScreen
from lib.client_flows.flow_cache import purge_client_flow_cache
from lib.client_flows.helper import iter_flow_screen_required_parameters
from lib.client_flows.screen_cache import ClientScreen, get_client_screen
from lib.client_flows.screen_schema import UNSAFE_SCREEN_SCHEMA_TYPES
from models import StandardErrorResponse
from resources.patch.docs import (
    PATCH_DOCS,
    PRECONDITION_DOCS,
    create_description,
    create_responses,
)
from resources.patch.exceptions import (
    PreconditionFailedException,
    SubresourceMissingException,
    UpdateFailedException,
)
from resources.patch.handle_patch import handle_patch
from resources.patch.not_set import NotSetEnum
from resources.patch.precondition import (
    check_simple_precondition,
)
from resources.patch.query import Query
from openapi_schema_validator import OAS30Validator

from users.me.screens.lib.standard_parameters import get_standard_parameter_schema

router = APIRouter()


class ClientFlowPreconditionModel(BaseModel):
    slug: str = Field(default_factory=lambda: NotSetEnum.NOT_SET)
    name: Optional[str] = Field(default_factory=lambda: NotSetEnum.NOT_SET)
    description: Optional[str] = Field(default_factory=lambda: NotSetEnum.NOT_SET)
    client_schema: dict = Field(default_factory=lambda: NotSetEnum.NOT_SET)
    server_schema: dict = Field(default_factory=lambda: NotSetEnum.NOT_SET)
    replaces: bool = Field(default_factory=lambda: NotSetEnum.NOT_SET)
    screens: List[ClientFlowScreen] = Field(default_factory=lambda: NotSetEnum.NOT_SET)
    flags: int = Field(default_factory=lambda: NotSetEnum.NOT_SET)
    created_at: float = Field(default_factory=lambda: NotSetEnum.NOT_SET)


class ClientFlowPatchModel(BaseModel):
    slug: str = Field(default_factory=lambda: NotSetEnum.NOT_SET)
    name: Optional[str] = Field(default_factory=lambda: NotSetEnum.NOT_SET)
    description: Optional[str] = Field(default_factory=lambda: NotSetEnum.NOT_SET)
    client_schema: dict = Field(default_factory=lambda: NotSetEnum.NOT_SET)
    server_schema: dict = Field(default_factory=lambda: NotSetEnum.NOT_SET)
    replaces: bool = Field(default_factory=lambda: NotSetEnum.NOT_SET)
    screens: List[ClientFlowScreen] = Field(default_factory=lambda: NotSetEnum.NOT_SET)
    flags: int = Field(default_factory=lambda: NotSetEnum.NOT_SET)


class PatchClientFlowRequest(BaseModel):
    uid: str = Field(description="The uid of the client flow to update")
    precondition: ClientFlowPreconditionModel = Field(
        default_factory=lambda: ClientFlowPreconditionModel.model_validate({}),
        description=PRECONDITION_DOCS,
    )
    patch: ClientFlowPatchModel = Field(
        default_factory=lambda: ClientFlowPatchModel.model_validate({}),
        description=PATCH_DOCS,
    )


ERROR_404_TYPES = Literal["client_flow_not_found", "client_screen_not_found"]
ERROR_409_TYPES = Literal[
    "flow_is_unsafe",
    "client_flow_slug_exists",
    "screen_parameters_mismatch",
]


@router.patch(
    "/",
    response_model=ClientFlow,
    description=create_description("client flow"),
    responses=create_responses(ERROR_404_TYPES, ERROR_409_TYPES),
)
async def patch_client_flow(
    args: PatchClientFlowRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        try:
            await ensure_cache_purgable(itgs, args.uid, args.precondition, args.patch)
            flow_screens = await check_flow_screens(
                itgs, args.uid, args.patch, args.precondition
            )
        except SubresourceMissingException as e:
            return e.to_response()
        except PreconditionFailedException as e:
            return Response(
                content=StandardErrorResponse[str](
                    type="precondition_failed",
                    message=(
                        "the precondition was not met:\n"
                        f"- {e.field}: expected {e.expected}, but was {e.actual}"
                    ),
                ).model_dump_json(),
                status_code=412,
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        patch_queries = do_patch(
            args.uid,
            args.precondition,
            args.patch,
            flow_screens=flow_screens,
        )
        is_patch = not not patch_queries
        queries = [
            *check_preconditions(args.uid, args.precondition, flow_screens),
            *check_conflicts(args.uid, args.patch),
            *check_subresources(args.patch, flow_screens=flow_screens),
            *patch_queries,
            do_read(args.uid),
        ]

        success, read_result_or_error_response = await handle_patch(
            itgs, queries, is_patch
        )
        if not success:
            return read_result_or_error_response

        read_result = cast(ResultItem, read_result_or_error_response)

        flow = await parse_read_result(itgs, read_result)
        if patch_queries:
            if args.patch.slug is not NotSetEnum.NOT_SET:
                assert args.precondition.slug is not NotSetEnum.NOT_SET
                await purge_client_flow_cache(itgs, slug=args.precondition.slug)

            await purge_client_flow_cache(itgs, slug=flow.slug)

        return Response(
            content=flow.__pydantic_serializer__.to_json(flow),
            status_code=200,
            headers={
                "Content-Type": "application/json; charset=utf-8",
            },
        )


@dataclass
class ClientFlowScreenInfo:
    uid: str
    slug: str
    schema: str


@dataclass
class ClientFlowScreensInfo:
    unchanged: List[ClientFlowScreenInfo]


STRING_FORMATTABLE_TYPES = {"integer", "number", "string", "boolean"}


async def ensure_cache_purgable(
    itgs: Itgs,
    uid: str,
    precondition: ClientFlowPreconditionModel,
    patch: ClientFlowPatchModel,
) -> None:
    if patch.slug is NotSetEnum.NOT_SET or precondition.slug is not NotSetEnum.NOT_SET:
        return

    conn = await itgs.conn()
    cursor = conn.cursor("weak")
    response = await cursor.execute(
        "SELECT slug FROM client_flows WHERE uid = ?",
        (uid,),
    )
    if not response.results:
        raise SubresourceMissingException[ERROR_404_TYPES](
            "client_flow_not_found", "client_flow", uid
        )

    precondition.slug = response.results[0][0]


async def check_flow_screens(
    itgs: Itgs,
    uid: str,
    patch: ClientFlowPatchModel,
    precondition: ClientFlowPreconditionModel,
) -> ClientFlowScreensInfo:
    """If the patch doesn't change the screens, returns a blank precondition for
    the update. Otherwise, this will verify:

    - the flow only references standard parameters that actually exist
    - the client_schema includes an example that actually matches the client_schema
    - the server_schema includes an example that actually matches the server_schema
    - the flow only references client parameters it requires in the client_schema
    - the flow only references server parameters it requires in the server_schema
    - the flow only references screens that actually exist
    - the screen input parameters for each screen will match that screens schema
    - the flow is secure in the sense it doesn't use untrusted inputs for sensitive
      screen parameters

    These checks are only valid so long as the precondition holds true (it may
    be strengthened by this function), plus all the referenced screens in
    `screens` aren't meaningfully changed.
    """
    if (
        patch.client_schema is NotSetEnum.NOT_SET
        and patch.server_schema is NotSetEnum.NOT_SET
        and patch.screens is NotSetEnum.NOT_SET
    ):
        return ClientFlowScreensInfo(unchanged=[])

    client_schema = (
        patch.client_schema
        if patch.client_schema is not NotSetEnum.NOT_SET
        else precondition.client_schema
    )
    server_schema = (
        patch.server_schema
        if patch.server_schema is not NotSetEnum.NOT_SET
        else precondition.server_schema
    )
    screens = (
        patch.screens
        if patch.screens is not NotSetEnum.NOT_SET
        else precondition.screens
    )

    if (
        client_schema is NotSetEnum.NOT_SET
        or server_schema is NotSetEnum.NOT_SET
        or screens is NotSetEnum.NOT_SET
    ):
        conn = await itgs.conn()
        cursor = conn.cursor("weak")
        response = await cursor.execute(
            "SELECT client_schema, server_schema, screens FROM client_flows WHERE uid = ?",
            (uid,),
        )
        if not response.results:
            raise SubresourceMissingException[ERROR_404_TYPES](
                "client_flow_not_found", "client_flow", uid
            )

        row = response.results[0]
        actual_client_schema = cast(dict, json.loads(row[0]))
        actual_server_schema = cast(dict, json.loads(row[1]))
        actual_screens = decode_flow_screens(row[2])

        if client_schema is NotSetEnum.NOT_SET:
            precondition.client_schema = actual_client_schema
            client_schema = actual_client_schema
        else:
            expected = json.dumps(client_schema, sort_keys=True)
            actual = json.dumps(actual_client_schema, sort_keys=True)
            if expected != actual:
                raise PreconditionFailedException(
                    "client_schema",
                    expected,
                    actual,
                )

        if server_schema is NotSetEnum.NOT_SET:
            precondition.server_schema = actual_server_schema
            server_schema = actual_server_schema
        else:
            expected = json.dumps(server_schema, sort_keys=True)
            actual = json.dumps(actual_server_schema, sort_keys=True)
            if expected != actual:
                raise PreconditionFailedException(
                    "server_schema",
                    expected,
                    actual,
                )

        if screens is NotSetEnum.NOT_SET:
            precondition.screens = actual_screens
            screens = actual_screens
        else:
            expected = etag_flow_screens(screens)
            actual = etag_flow_screens(actual_screens)

            if expected != actual:
                raise PreconditionFailedException(
                    "screens",
                    expected,
                    actual,
                )

    try:
        OAS30Validator.check_schema(client_schema)
    except:
        raise PreconditionFailedException("client_schema", "valid", "invalid")

    try:
        OAS30Validator.check_schema(server_schema)
    except:
        raise PreconditionFailedException("server_schema", "valid", "invalid")

    client_schema_obj = cast(Validator, OAS30Validator(client_schema))
    server_schema_obj = cast(Validator, OAS30Validator(server_schema))

    if client_schema.get("example") is None:
        raise PreconditionFailedException(
            "client_schema", "to have an example", "missing example"
        )
    if (
        client_schema_example_err := jsonschema.exceptions.best_match(
            client_schema_obj.iter_errors(client_schema["example"])
        )
    ) is not None:
        raise PreconditionFailedException(
            "client_schema", "to have a valid example", str(client_schema_example_err)
        )

    if server_schema.get("example") is None:
        raise PreconditionFailedException(
            "server_schema", "to have an example", "missing example"
        )
    if (
        server_schema_example_err := jsonschema.exceptions.best_match(
            server_schema_obj.iter_errors(server_schema["example"])
        )
    ) is not None:
        raise PreconditionFailedException(
            "server_schema", "to have a valid example", str(server_schema_example_err)
        )

    screens_by_slug: Dict[str, ClientScreen] = dict()
    for idx, flow_screen in enumerate(screens):
        screen = screens_by_slug.get(flow_screen.screen.slug)
        if screen is None:
            screen = await get_client_screen(itgs, slug=flow_screen.screen.slug)
            if screen is None:
                raise SubresourceMissingException[ERROR_404_TYPES](
                    "client_screen_not_found",
                    f"screens[{idx}].screen.slug",
                    flow_screen.screen.slug,
                )
            screens_by_slug[flow_screen.screen.slug] = screen

        for (
            input_path,
            output_path,
            usage_type,
            variable_parameter_idx,
        ) in iter_flow_screen_required_parameters(flow_screen):
            produced_schema = _get_flow_screen_param_schema(
                f"screens[{idx}].screen.variable[{variable_parameter_idx}]",
                client_schema,
                server_schema,
                input_path,
            )
            produced_example = produced_schema.get("example")
            if produced_example is None:
                raise PreconditionFailedException(
                    f"screens[{idx}].screen.variable[{variable_parameter_idx}] input {input_path}",
                    "to have an example",
                    "missing an example",
                )

            try:
                OAS30Validator.check_schema(produced_schema)
            except:
                raise PreconditionFailedException(
                    f"screens[{idx}].screen.variable[{variable_parameter_idx}] input {input_path}",
                    "to have a valid schema",
                    "invalid schema",
                )

            produced_schema_obj = cast(Validator, OAS30Validator(produced_schema))
            if (
                produced_example_err := jsonschema.exceptions.best_match(
                    produced_schema_obj.iter_errors(produced_example)
                )
                is not None
            ):
                raise PreconditionFailedException(
                    f"screens[{idx}].screen.variable[{variable_parameter_idx}] input {input_path}",
                    "to have a valid example",
                    str(produced_example_err),
                )

            target_schema = _get_param_schema_from_schema(
                f"screens[{idx}].screen.variable[{variable_parameter_idx}] target for {input_path}",
                screen.raw_schema,
                output_path,
            )
            target_type = target_schema.get("type")

            if usage_type == "string_formattable":
                produced_type = produced_schema.get("type")
                if produced_type not in STRING_FORMATTABLE_TYPES:
                    raise PreconditionFailedException(
                        f"screens[{idx}].screen.variable[{variable_parameter_idx}] input {input_path}",
                        "to be a string, number, integer, or boolean",
                        f"not a {produced_type}",
                    )
                if target_type != "string":
                    raise PreconditionFailedException(
                        f"screens[{idx}].screen.variable[{variable_parameter_idx}] input {input_path}",
                        "'string'",
                        f"{target_type!r}",
                    )

                if input_path[0] != "server" and (
                    (target_type, target_schema.get("format"))
                    in UNSAFE_SCREEN_SCHEMA_TYPES
                ):
                    raise PreconditionFailedException(
                        f"screens[{idx}].screen.variable[{variable_parameter_idx}] input {input_path}",
                        "to have a safe target",
                        f"unsafe type/format: {target_type!r}, {target_schema.get('format')!r}",
                    )
            elif usage_type == "copy":
                OAS30Validator.check_schema(target_schema)
                target_schema_obj = cast(Validator, OAS30Validator(target_schema))
                if target_err := jsonschema.exceptions.best_match(
                    target_schema_obj.iter_errors(produced_example)
                ):
                    raise PreconditionFailedException(
                        f"screens[{idx}].screen.variable[{variable_parameter_idx}] input {input_path}",
                        f"to have the produced example {produced_example!r} be valid for the target schema {target_schema!r}",
                        str(target_err),
                    )

                if input_path[0] != "server" and (
                    (target_type, target_schema.get("format"))
                    in UNSAFE_SCREEN_SCHEMA_TYPES
                ):
                    raise PreconditionFailedException(
                        f"screens[{idx}].screen.variable[{variable_parameter_idx}] input {input_path}",
                        "to have a safe target",
                        f"unsafe type/format: {target_type!r}, {target_schema.get('format')!r}",
                    )

                if (
                    produced_schema.get("nullable", False) is True
                    and target_schema.get("nullable", False) is not True
                ):
                    raise PreconditionFailedException(
                        f"screens[{idx}].screen.variable[{variable_parameter_idx}] input {input_path}",
                        "to have a nullable target, given that the input is nullable",
                        "not nullable",
                    )
            else:
                raise Exception(f"unknown usage type: {usage_type}")

    return ClientFlowScreensInfo(
        unchanged=[
            ClientFlowScreenInfo(
                uid=screen.uid,
                slug=screen.slug,
                schema=json.dumps(screen.raw_schema, sort_keys=True),
            )
            for screen in screens_by_slug.values()
        ]
    )


def _get_flow_screen_param_schema(
    src: str, client_schema: dict, server_schema: dict, param: List[str]
) -> dict:
    if len(param) < 1:
        raise PreconditionFailedException(
            src, "not to be an empty parameter", "an empty parameter"
        )

    if param[0] == "standard":
        res = get_standard_parameter_schema(param[1:])
        if res is None:
            raise PreconditionFailedException(
                src,
                "to reference a valid parameter",
                f"{param}",
            )
        return res
    elif param[0] == "client":
        return _get_param_schema_from_schema(src, client_schema, param[1:], level=1)
    elif param[0] == "server":
        return _get_param_schema_from_schema(src, server_schema, param[1:], level=1)
    else:
        raise PreconditionFailedException(
            src,
            "to reference a standard, client, or server parameter",
            "an unknown parameter",
        )


def _get_param_schema_from_schema(
    src: str, schema: dict, param: List[str], *, level: int = 0
) -> dict:
    current = schema
    stack = param.copy()
    while len(stack) > 1:
        if not isinstance(current, dict):
            raise PreconditionFailedException(
                src,
                f"to reference a valid parameter (at level {level})",
                f"{param} (not a dict @ {param[:level]})",
            )
        if current.get("type") != "object":
            raise PreconditionFailedException(
                src,
                f"to reference a valid parameter (at level {level})",
                f"{param} (not an object @ {param[:level]})",
            )
        if current.get("nullable", False) is not False:
            raise PreconditionFailedException(
                src,
                f"to reference a valid parameter (at level {level})",
                f"{param} (nullable @ {param[:level]})",
            )
        required = current.get("required")
        if required is None:
            raise PreconditionFailedException(
                src,
                f"to reference a valid parameter (at level {level})",
                f"{param} (no required @ {param[:level]})",
            )
        if not isinstance(required, list):
            raise PreconditionFailedException(
                src,
                f"to reference a valid parameter (at level {level})",
                f"{param} (required not a list @ {param[:level]})",
            )
        if stack[0] not in required:
            raise PreconditionFailedException(
                src,
                f"to reference a valid parameter (at level {level})",
                f"{param} (required {stack[0]} missing @ {param[:level]})",
            )

        properties = current.get("properties")
        if properties is None:
            raise PreconditionFailedException(
                src,
                f"to reference a valid parameter (at level {level})",
                f"{param} (no properties @ {param[:level]})",
            )

        if not isinstance(properties, dict):
            raise PreconditionFailedException(
                src,
                f"to reference a valid parameter (at level {level})",
                f"{param} (properties not a dict @ {param[:level]})",
            )

        current = properties.get(stack[0])
        if current is None:
            raise PreconditionFailedException(
                src,
                f"to reference a valid parameter (at level {level})",
                f"{param} (no property {stack[0]} @ {param[:level]})",
            )
        if not isinstance(current, dict):
            raise PreconditionFailedException(
                src,
                f"to reference a valid parameter (at level {level})",
                f"{param} (property {stack[0]} not a dict @ {param[:level]})",
            )

        level += 1
        stack = stack[1:]

    return current


def check_preconditions(
    uid: str,
    preconditions: ClientFlowPreconditionModel,
    flow_screens: ClientFlowScreensInfo,
) -> List[Query]:
    simple = partial(check_simple_precondition, "client_flows", uid)
    return [
        *simple("slug", preconditions.slug),
        *simple("name", preconditions.name),
        *simple("description", preconditions.description),
        *simple(
            "client_schema", json.dumps(preconditions.client_schema, sort_keys=True)
        ),
        *simple(
            "server_schema", json.dumps(preconditions.server_schema, sort_keys=True)
        ),
        *simple("replaces", preconditions.replaces),
        *simple("screens", encode_flow_screens(preconditions.screens)),
        *simple("flags", preconditions.flags),
        *simple("created_at", preconditions.created_at),
        *[
            a
            for screen in flow_screens.unchanged
            for a in [
                *check_simple_precondition(
                    "client_screens", screen.uid, "slug", screen.slug
                ),
                *check_simple_precondition(
                    "client_screens", screen.uid, "schema", screen.schema
                ),
            ]
        ],
    ]


def check_conflicts(uid: str, patch: ClientFlowPatchModel) -> List[Query]:
    if patch.slug is NotSetEnum.NOT_SET:
        return []

    async def handle(r: ResultItem):
        if r.results:
            raise PreconditionFailedException(
                "slug",
                "to be unique",
                "not unique",
            )

    return [
        Query(
            "SELECT 1 FROM client_flows WHERE slug = ? AND uid <> ?",
            [patch.slug, uid],
            handle,
        )
    ]


def check_subresources(
    patch: ClientFlowPatchModel, *, flow_screens: ClientFlowScreensInfo
) -> List[Query]:
    """Verifies that any screens referenced in the new client flow haven't changed
    since they were initially checked in `check_flow_screens`, as a list of queries
    so that we can raise the appropriate error
    """

    async def handle(idx: int, item: ResultItem):
        if not item.results:
            raise SubresourceMissingException[ERROR_404_TYPES](
                "client_screen_not_found",
                f"screens[{idx}].screen.slug",
                patch.screens[idx].screen.slug,
            )

        expected = flow_screens.unchanged[idx]
        row_uid = item.results[0][0]
        row_schema = item.results[0][1]

        if row_uid != expected.uid or row_schema != expected.schema:
            raise PreconditionFailedException(
                f"screens[{idx}].screen.slug -> client_screens.slug",
                f"to have uid={expected.uid}, schema={expected.schema}",
                f"uid={row_uid}, schema={row_schema}",
            )

    return [
        Query(
            sql="SELECT uid, schema FROM client_screens WHERE slug = ?",
            args=[screen.slug],
            process_result=partial(handle, idx),
        )
        for idx, screen in enumerate(flow_screens.unchanged)
    ]


def _checked_client_flows(
    uid: str,
    patch: ClientFlowPatchModel,
    precondition: ClientFlowPreconditionModel,
    qargs: list,
    *,
    flow_screens: ClientFlowScreensInfo,
) -> str:
    """Returns an expression like

    checked_client_flows(id, uid) AS (...)

    which will be populated with 0 or 1 rows, depending on whether the
    client flow meets the preconditions

    Args:
        uid (str): the uid of the client flow; if a row is populated in
            checked_client_flows, it will be this uid
        patch (ClientFlowPatchSimple): the patch to apply
        precondition (ClientFlowPreconditionSimple): the precondition to check
        qargs (list): the list of arguments to the query
        flow_screens (ClientFlowScreensInfo): the screens that must not have
            changed
    """

    result = io.StringIO()
    result.write("checked_client_flows(id, uid) AS (SELECT id, uid FROM client_flows")

    result.write(" WHERE uid = ?")
    qargs.append(uid)

    for unch in flow_screens.unchanged:
        result.write(
            " AND EXISTS (SELECT 1 FROM client_screens AS cs WHERE cs.slug = ? AND cs.uid = ? AND cs.schema = ?)"
        )
        qargs.extend([unch.slug, unch.uid, unch.schema])

    if precondition.slug is not NotSetEnum.NOT_SET:
        result.write(" AND slug = ?")
        qargs.append(precondition.slug)

    if patch.slug is not NotSetEnum.NOT_SET:
        result.write(
            " AND NOT EXISTS (SELECT 1 FROM client_flows AS cf WHERE cf.slug = ? AND cf.uid <> ?)"
        )
        qargs.extend([patch.slug, uid])

    if precondition.name is not NotSetEnum.NOT_SET:
        if precondition.name is None:
            result.write(" AND name IS NULL")
        else:
            result.write(" AND name = ?")
            qargs.append(precondition.name)

    if precondition.description is not NotSetEnum.NOT_SET:
        if precondition.description is None:
            result.write(" AND description IS NULL")
        else:
            result.write(" AND description = ?")
            qargs.append(precondition.description)

    if precondition.client_schema is not NotSetEnum.NOT_SET:
        result.write(" AND client_schema = ?")
        qargs.append(json.dumps(precondition.client_schema, sort_keys=True))

    if precondition.server_schema is not NotSetEnum.NOT_SET:
        result.write(" AND server_schema = ?")
        qargs.append(json.dumps(precondition.server_schema, sort_keys=True))

    if precondition.replaces is not NotSetEnum.NOT_SET:
        result.write(" AND replaces = ?")
        qargs.append(int(precondition.replaces))

    if precondition.screens is not NotSetEnum.NOT_SET:
        result.write(" AND screens = ?")
        qargs.append(encode_flow_screens(precondition.screens))

    if precondition.flags is not NotSetEnum.NOT_SET:
        result.write(" AND flags = ?")
        qargs.append(precondition.flags)

    if precondition.created_at is not NotSetEnum.NOT_SET:
        result.write(" AND created_at = ?")
        qargs.append(precondition.created_at)

    result.write(")")
    return result.getvalue()


def do_patch(
    uid: str,
    preconditions: ClientFlowPreconditionModel,
    patch: ClientFlowPatchModel,
    *,
    flow_screens: ClientFlowScreensInfo,
) -> List[Query]:
    updates: List[str] = []
    update_qargs: List[Any] = []

    if patch.slug is not NotSetEnum.NOT_SET:
        updates.append("slug = ?")
        update_qargs.append(patch.slug)

    if patch.name is not NotSetEnum.NOT_SET:
        if patch.name is None:
            updates.append("name = NULL")
        else:
            updates.append("name = ?")
            update_qargs.append(patch.name)

    if patch.description is not NotSetEnum.NOT_SET:
        if patch.description is None:
            updates.append("description = NULL")
        else:
            updates.append("description = ?")
            update_qargs.append(patch.description)

    if patch.client_schema is not NotSetEnum.NOT_SET:
        updates.append("client_schema = ?")
        update_qargs.append(json.dumps(patch.client_schema, sort_keys=True))

    if patch.server_schema is not NotSetEnum.NOT_SET:
        updates.append("server_schema = ?")
        update_qargs.append(json.dumps(patch.server_schema, sort_keys=True))

    if patch.replaces is not NotSetEnum.NOT_SET:
        updates.append("replaces = ?")
        update_qargs.append(int(patch.replaces))

    if patch.screens is not NotSetEnum.NOT_SET:
        updates.append("screens = ?")
        update_qargs.append(encode_flow_screens(patch.screens))

    if patch.flags is not NotSetEnum.NOT_SET:
        updates.append("flags = ?")
        update_qargs.append(patch.flags)

    if not updates:
        return []

    update_sql = ", ".join(updates)

    query = io.StringIO()
    qargs = []

    query.write("WITH ")
    query.write(
        _checked_client_flows(
            uid,
            patch,
            preconditions,
            qargs,
            flow_screens=flow_screens,
        )
    )
    query.write(" UPDATE client_flows SET ")
    query.write(update_sql)
    qargs.extend(update_qargs)
    query.write(
        " FROM checked_client_flows WHERE client_flows.id = checked_client_flows.id"
    )

    async def _check(r: ResultItem) -> None:
        if r.rows_affected != 1:
            if r.rows_affected is not None and r.rows_affected > 0:
                await handle_warning(
                    f"{__name__}:multiple_rows_affected",
                    f"expected to update 0 or 1 rows, but updated {r.rows_affected}",
                    is_urgent=True,
                )
            raise UpdateFailedException()

    return [Query(query.getvalue(), qargs, _check)]


def do_read(uid: str) -> Query:
    async def _check(r: ResultItem) -> None:
        if not r.results:
            raise SubresourceMissingException[ERROR_404_TYPES](
                "client_flow_not_found", "client_flow", uid
            )

    return Query(
        sql=f"""
{STANDARD_CLIENT_FLOW_READ_QUERY}
WHERE uid = ?
        """,
        args=[uid],
        process_result=_check,
    )


async def parse_read_result(itgs: Itgs, r: ResultItem) -> ClientFlow:
    assert r.results

    row = r.results[0]
    return await parse_client_flow_read_row(itgs, row)
