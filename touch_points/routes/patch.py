import base64
from functools import partial
import gzip
import io
import json
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import (
    Annotated,
    Any,
    List,
    Optional,
    Literal,
    Union,
    cast,
)
from auth import auth_admin
from rqdb.result import ResultItem
from error_middleware import handle_warning
from itgs import Itgs
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
from resources.patch.not_set import NotSet, NotSetEnum
from resources.patch.precondition import (
    check_simple_precondition,
)
from resources.patch.query import Query
from touch_points.lib.etag import get_messages_etag
from touch_points.lib.schema.check_touch_point_schema import check_touch_point_schema
from touch_points.lib.touch_points import TouchPointMessages
from touch_points.routes.read import TouchPointSelectionStrategy, TouchPointWithMessages
from user_safe_error import UserSafeError

router = APIRouter()


class TouchPointPreconditionModel(BaseModel):
    event_slug: str = Field(default_factory=lambda: NotSetEnum.NOT_SET)
    event_schema: Any = Field(default_factory=lambda: NotSetEnum.NOT_SET)
    selection_strategy: TouchPointSelectionStrategy = Field(
        default_factory=lambda: NotSetEnum.NOT_SET
    )
    messages_etag: str = Field(default_factory=lambda: NotSetEnum.NOT_SET)
    created_at: float = Field(default_factory=lambda: NotSetEnum.NOT_SET)


class TouchPointPatchModel(BaseModel):
    event_slug: str = Field(default_factory=lambda: NotSetEnum.NOT_SET)
    event_schema: Any = Field(default_factory=lambda: NotSetEnum.NOT_SET)
    selection_strategy: TouchPointSelectionStrategy = Field(
        default_factory=lambda: NotSetEnum.NOT_SET
    )
    messages: TouchPointMessages = Field(default_factory=lambda: NotSetEnum.NOT_SET)


class PatchTouchPointRequest(BaseModel):
    uid: str = Field(description="The uid of the touch point to update")
    precondition: TouchPointPreconditionModel = Field(
        default_factory=lambda: TouchPointPreconditionModel.model_validate({}),
        description=PRECONDITION_DOCS,
    )
    patch: TouchPointPatchModel = Field(
        default_factory=lambda: TouchPointPatchModel.model_validate({}),
        description=PATCH_DOCS,
    )


ERROR_404_TYPES = Literal["touch_point_not_found"]
ERROR_409_TYPES = Literal["schema_fails_validation", "messages_dont_match_schema"]


@router.patch(
    "/",
    response_model=TouchPointWithMessages,
    description=create_description("touch point"),
    responses=create_responses(ERROR_404_TYPES, ERROR_409_TYPES),
)
async def patch_touch_point(
    args: PatchTouchPointRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        try:
            messages_precondition = await get_messages_precondition(
                itgs, args.uid, args.precondition
            )
            messages_precondition = await _check_schema_and_messages(
                itgs,
                uid=args.uid,
                precondition=args.precondition,
                patch=args.patch,
                messages_precondition=messages_precondition,
            )
        except SubresourceMissingException as e:
            return e.to_response()
        except PreconditionFailedException as e:
            return Response(
                content=StandardErrorResponse[str](
                    type="precondition_failed",
                    message=(
                        "the precondition was not met:\n"
                        f"- {e.field}: expected {e.expected!r}, but was {e.actual!r}"
                    ),
                ).model_dump_json(),
                status_code=412,
                headers={"Content-Type": "application/json; charset=utf-8"},
            )
        except UserSafeError as e:
            return e.response

        patch_queries = do_patch(
            args.uid,
            args.precondition,
            args.patch,
            messages_precondition=messages_precondition,
        )
        is_patch = not not patch_queries
        queries = [
            *check_preconditions(args.uid, args.precondition, messages_precondition),
            *check_subresources(args.patch),
            *patch_queries,
            do_read(args.uid),
        ]

        success, read_result_or_error_response = await handle_patch(
            itgs, queries, is_patch
        )
        if not success:
            return read_result_or_error_response

        read_result = cast(ResultItem, read_result_or_error_response)

        touch_point = await parse_read_result(itgs, read_result)
        return Response(
            content=touch_point.__pydantic_serializer__.to_json(touch_point),
            status_code=200,
            headers={
                "Content-Type": "application/json; charset=utf-8",
            },
        )


async def get_messages_precondition(
    itgs: Itgs,
    uid: str,
    preconditions: TouchPointPreconditionModel,
    *,
    read_consistency: Literal["weak", "none"] = "none",
) -> Union[str, NotSet]:
    if preconditions.messages_etag is NotSetEnum.NOT_SET:
        return NotSetEnum.NOT_SET

    conn = await itgs.conn()
    cursor = conn.cursor(read_consistency)
    response = await cursor.execute(
        "SELECT messages FROM touch_points WHERE uid = ?", (uid,)
    )
    if not response.results:
        if read_consistency == "none":
            return await get_messages_precondition(
                itgs, uid, preconditions, read_consistency="weak"
            )
        raise SubresourceMissingException[ERROR_404_TYPES](
            "touch_point_not_found", "touch_point", uid
        )

    messages_raw = cast(str, response.results[0][0])
    current_etag = get_messages_etag(messages_raw)
    if current_etag == preconditions.messages_etag:
        return messages_raw

    if read_consistency == "none":
        return await get_messages_precondition(
            itgs, uid, preconditions, read_consistency="weak"
        )

    raise PreconditionFailedException(
        "messages_etag", preconditions.messages_etag, current_etag
    )


async def _check_schema_and_messages(
    itgs: Itgs,
    /,
    *,
    uid: str,
    precondition: TouchPointPreconditionModel,
    patch: TouchPointPatchModel,
    messages_precondition: Union[str, NotSet],
) -> Union[str, NotSet]:
    """Check that the schema is a valid OpenAPI 3.0.3 object and meets our additional
    requirements (examples, types and formats), and the substitutions would be likely
    to succeed given the event schema

    This mutates the precondition to enforce the event schema / messages match the
    ones we verified against. Returns the new messages precondition
    """
    event_schema = patch.event_schema
    if event_schema is NotSetEnum.NOT_SET:
        event_schema = precondition.event_schema

    messages = patch.messages
    if (
        messages is NotSetEnum.NOT_SET
        and messages_precondition is not NotSetEnum.NOT_SET
    ):
        messages = TouchPointMessages.model_validate_json(
            gzip.decompress(base64.b85decode(messages_precondition))
        )

    if event_schema is NotSetEnum.NOT_SET and messages is NotSetEnum.NOT_SET:
        # Since the query doesn't check or change the event schema or messages,
        # there's no need to check them
        return NotSetEnum.NOT_SET

    if event_schema is NotSetEnum.NOT_SET:
        conn = await itgs.conn()
        cursor = conn.cursor("weak")
        response = await cursor.execute(
            "SELECT event_schema FROM touch_points WHERE uid = ?", (uid,)
        )
        if not response.results:
            raise SubresourceMissingException[ERROR_404_TYPES](
                "touch_point_not_found", "touch_point", uid
            )
        event_schema = json.loads(response.results[0][0])
        precondition.event_schema = event_schema

    if messages is NotSetEnum.NOT_SET:
        conn = await itgs.conn()
        cursor = conn.cursor("weak")
        response = await cursor.execute(
            "SELECT messages FROM touch_points WHERE uid = ?", (uid,)
        )
        if not response.results:
            raise SubresourceMissingException[ERROR_404_TYPES](
                "touch_point_not_found", "touch_point", uid
            )
        messages_precondition = cast(str, response.results[0][0])
        messages = TouchPointMessages.model_validate_json(
            gzip.decompress(base64.b85decode(messages_precondition))
        )

    result = await check_touch_point_schema(
        itgs, schema=event_schema, messages=messages
    )
    if result.success is True:
        return messages_precondition

    raise UserSafeError(
        message=result.message,
        response=Response(
            content=StandardErrorResponse[ERROR_409_TYPES](
                type=(
                    "schema_fails_validation"
                    if result.category == "schema"
                    else "messages_dont_match_schema"
                ),
                message=result.message,
            ).model_dump_json(),
            status_code=409,
            headers={
                "Content-Type": "application/json; charset=utf-8",
            },
        ),
    )


def _check_messages(
    uid: str,
    preconditions: TouchPointPreconditionModel,
    messages_precondition: Union[str, NotSet],
) -> List[Query]:
    """We use a custom precondition check to avoid including the whole messages in the error"""
    if messages_precondition is NotSetEnum.NOT_SET:
        return []

    async def _check(item: ResultItem) -> None:
        if item.results:
            actual_raw = cast(str, item.results[0][0])
            actual_etag = get_messages_etag(actual_raw)
            raise PreconditionFailedException(
                "messages_etag", preconditions.messages_etag, actual_etag
            )

    return [
        Query(
            f"SELECT messages FROM touch_points WHERE uid=? AND messages <> ?",
            [uid, messages_precondition],
            _check,
        )
    ]


def check_preconditions(
    uid: str,
    preconditions: TouchPointPreconditionModel,
    messages_precondition: Union[str, NotSet],
) -> List[Query]:
    simple = partial(check_simple_precondition, "touch_points", uid)
    return [
        *simple("event_slug", preconditions.event_slug),
        *simple("event_schema", json.dumps(preconditions.event_schema, sort_keys=True)),
        *simple("selection_strategy", preconditions.selection_strategy),
        *_check_messages(uid, preconditions, messages_precondition),
    ]


def check_subresources(patch: TouchPointPatchModel) -> List[Query]:
    return []


def _checked_touch_points(
    uid: str,
    patch: TouchPointPatchModel,
    precondition: TouchPointPreconditionModel,
    qargs: list,
    *,
    messages_precondition: Union[str, NotSet],
) -> str:
    """Returns an expression like

    checked_touch_points(id, uid) AS (...)

    which will be populated with 0 or 1 rows, depending on whether the
    touch point meets the preconditions

    Args:
        uid (str): the uid of the touch point; if a row is populated in
            checked_touch_points, it will be this uid
        patch (TouchPointPatchSimple): the patch to apply
        precondition (TouchPointPreconditionSimple): the precondition to check
        qargs (list): the list of arguments to the query
        messages_precondition (str or NotSet): if there is a messages_etag
            precondition, the messages that corresponds to that etag
    """

    result = io.StringIO()
    result.write("checked_touch_points(id, uid) AS (SELECT id, uid FROM touch_points")

    result.write(" WHERE uid = ?")
    qargs.append(uid)

    if precondition.event_slug is not NotSetEnum.NOT_SET:
        result.write(" AND event_slug = ?")
        qargs.append(precondition.event_slug)

    if precondition.event_schema is not NotSetEnum.NOT_SET:
        result.write(" AND event_schema = ?")
        qargs.append(json.dumps(precondition.event_schema, sort_keys=True))

    if precondition.selection_strategy is not NotSetEnum.NOT_SET:
        result.write(" AND selection_strategy = ?")
        qargs.append(precondition.selection_strategy)

    if messages_precondition is not NotSetEnum.NOT_SET:
        result.write(" AND messages = ?")
        qargs.append(messages_precondition)

    if precondition.created_at is not NotSetEnum.NOT_SET:
        result.write(" AND created_at = ?")
        qargs.append(precondition.created_at)

    result.write(")")
    return result.getvalue()


def do_patch(
    uid: str,
    preconditions: TouchPointPreconditionModel,
    patch: TouchPointPatchModel,
    *,
    messages_precondition: Union[str, NotSet],
) -> List[Query]:
    updates: List[str] = []
    update_qargs: List[Any] = []

    if patch.event_slug is not NotSetEnum.NOT_SET:
        updates.append("event_slug = ?")
        update_qargs.append(patch.event_slug)

    if patch.event_schema is not NotSetEnum.NOT_SET:
        updates.append("event_schema = ?")
        update_qargs.append(json.dumps(patch.event_schema, sort_keys=True))

    if patch.selection_strategy is not NotSetEnum.NOT_SET:
        updates.append("selection_strategy = ?")
        update_qargs.append(patch.selection_strategy)

    if patch.messages is not NotSetEnum.NOT_SET:
        updates.append("messages = ?")
        update_qargs.append(
            base64.b85encode(
                gzip.compress(
                    TouchPointMessages.__pydantic_serializer__.to_json(patch.messages),
                    compresslevel=9,
                    mtime=0,
                )
            ).decode("ascii")
        )

    if not updates:
        return []

    update_sql = ", ".join(updates)

    query = io.StringIO()
    qargs = []

    query.write("WITH ")
    query.write(
        _checked_touch_points(
            uid,
            patch,
            preconditions,
            qargs,
            messages_precondition=messages_precondition,
        )
    )
    query.write(" UPDATE touch_points SET ")
    query.write(update_sql)
    qargs.extend(update_qargs)
    query.write(
        " FROM checked_touch_points WHERE touch_points.id = checked_touch_points.id"
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
                "touch_point_not_found", "touch_point", uid
            )

    return Query(
        sql="""
SELECT
    uid, event_slug, event_schema, selection_strategy, messages, created_at
FROM touch_points
WHERE uid = ?
        """,
        args=[uid],
        process_result=_check,
    )


async def parse_read_result(itgs: Itgs, r: ResultItem) -> TouchPointWithMessages:
    assert r.results

    row = r.results[0]
    messages_raw = cast(str, row[4])
    return TouchPointWithMessages(
        uid=row[0],
        event_slug=row[1],
        event_schema=json.loads(row[2]),
        selection_strategy=row[3],
        messages=TouchPointMessages.model_validate_json(
            gzip.decompress(base64.b85decode(messages_raw))
        ),
        messages_etag=get_messages_etag(messages_raw),
        created_at=row[5],
    )
