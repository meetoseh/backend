import io
import json
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import (
    Annotated,
    Any,
    Callable,
    Coroutine,
    Iterable,
    List,
    Optional,
    Literal,
    Union,
    cast,
    get_args,
)
from auth import auth_admin
from rqdb.result import ResultItem
from error_middleware import handle_warning
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from itgs import Itgs
from dataclasses import dataclass
from enum import Enum
from personalization.home.images.lib.internal_home_screen_image import (
    STANDARD_INTERNAL_HOME_SCREEN_IMAGE_ROW_SELECT_JOIN,
    InternalHomeScreenImage,
    InternalHomeScreenImageRow,
    parse_internal_home_screen_image_row,
)

router = APIRouter()


class _NotSetEnum(Enum):
    NOT_SET = "NOT_SET"


_NotSet = Literal[_NotSetEnum.NOT_SET]


@dataclass
class HomeScreenImagePreconditionSimple:
    image_file_uid: Union[str, _NotSet]
    darkened_image_file_uid: Union[str, _NotSet]
    start_time: Union[int, _NotSet]
    end_time: Union[int, _NotSet]
    flags: Union[int, _NotSet]
    dates: Union[List[str], None, _NotSet]
    created_at: Union[float, _NotSet]
    live_at: Union[float, _NotSet]


class HomeScreenImagePreconditionModel(BaseModel):
    image_file_uid: str = Field(default_factory=lambda: _NotSetEnum.NOT_SET)
    darkened_image_file_uid: str = Field(default_factory=lambda: _NotSetEnum.NOT_SET)
    start_time: int = Field(default_factory=lambda: _NotSetEnum.NOT_SET)
    end_time: int = Field(default_factory=lambda: _NotSetEnum.NOT_SET)
    flags: int = Field(default_factory=lambda: _NotSetEnum.NOT_SET)
    dates: Optional[List[str]] = Field(
        default_factory=lambda: _NotSetEnum.NOT_SET,
        description="This precondition is sensitive to the order",
    )
    created_at: float = Field(default_factory=lambda: _NotSetEnum.NOT_SET)
    live_at: float = Field(default_factory=lambda: _NotSetEnum.NOT_SET)

    def to_simple(self) -> HomeScreenImagePreconditionSimple:
        dumped = self.model_dump(exclude_unset=True)
        return HomeScreenImagePreconditionSimple(
            image_file_uid=dumped.get("image_file_uid", _NotSetEnum.NOT_SET),
            darkened_image_file_uid=dumped.get(
                "darkened_image_file_uid", _NotSetEnum.NOT_SET
            ),
            start_time=dumped.get("start_time", _NotSetEnum.NOT_SET),
            end_time=dumped.get("end_time", _NotSetEnum.NOT_SET),
            flags=dumped.get("flags", _NotSetEnum.NOT_SET),
            dates=dumped.get("dates", _NotSetEnum.NOT_SET),
            created_at=dumped.get("created_at", _NotSetEnum.NOT_SET),
            live_at=dumped.get("live_at", _NotSetEnum.NOT_SET),
        )


@dataclass
class HomeScreenImagePatchSimple:
    start_time: Union[int, _NotSet]
    end_time: Union[int, _NotSet]
    flags: Union[int, _NotSet]
    dates: Union[List[str], None, _NotSet]
    live_at: Union[float, _NotSet]


class HomeScreenImagePatchModel(BaseModel):
    start_time: int = Field(default_factory=lambda: _NotSetEnum.NOT_SET)
    end_time: int = Field(default_factory=lambda: _NotSetEnum.NOT_SET)
    flags: int = Field(default_factory=lambda: _NotSetEnum.NOT_SET)
    dates: Optional[List[str]] = Field(default_factory=lambda: _NotSetEnum.NOT_SET)
    live_at: float = Field(default_factory=lambda: _NotSetEnum.NOT_SET)

    def to_simple(self) -> HomeScreenImagePatchSimple:
        dumped = self.model_dump(exclude_unset=True)
        return HomeScreenImagePatchSimple(
            start_time=dumped.get("start_time", _NotSetEnum.NOT_SET),
            end_time=dumped.get("end_time", _NotSetEnum.NOT_SET),
            flags=dumped.get("flags", _NotSetEnum.NOT_SET),
            dates=dumped.get("dates", _NotSetEnum.NOT_SET),
            live_at=dumped.get("live_at", _NotSetEnum.NOT_SET),
        )


class PatchHomeScreenImageRequest(BaseModel):
    uid: str = Field(description="The uid of the home screen image to update")
    precondition: HomeScreenImagePreconditionModel = Field(
        default_factory=lambda: HomeScreenImagePreconditionModel.model_validate({}),
        description=(
            "The precondition for the update. The update will only go through "
            "if for each explicitly set field in the precondition, the current "
            "value of the field in the image being updated matches the value "
            "set in the precondition.\n\n"
            "Explicitly setting null in the precondition "
            "will require the field is null in the image being updated, whereas "
            "omitting a key in the precondition will allow any value in the course "
            "being updated."
        ),
    )
    patch: HomeScreenImagePatchModel = Field(
        default_factory=lambda: HomeScreenImagePatchModel.model_validate({}),
        description=(
            "The patch to apply to the home screen image. Any explicitly set field in the "
            "patch will be applied to the image being updated, provided the "
            "precondition is met."
        ),
    )


ERROR_404_TYPES = Literal["home_screen_image_not_found"]
ERROR_412_TYPES = Literal["precondition_failed"]

ERROR_404_RESPONSES = dict(
    (
        err_type,
        Response(
            status_code=404,
            content=StandardErrorResponse[ERROR_404_TYPES](
                type=err_type,
                message=f"there is no {err_type[:-len('_not_found')]} with that UID",
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        ),
    )
    for err_type in cast(Iterable[ERROR_404_TYPES], get_args(ERROR_404_TYPES))
)

# precondition_failed is generated on the fly to include the fields that failed


@router.patch(
    "/",
    response_model=InternalHomeScreenImage,
    responses={
        "404": {
            "description": "the home scree nimage does not exist",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        "412": {
            "description": "the precondition was not met",
            "model": StandardErrorResponse[ERROR_412_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def patch_home_screen_image(
    args: PatchHomeScreenImageRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Patches the home screen image with the given UID, optionally restricted by the
    given precondition.

    If no patches are requested, the preconditions are checked atomically with
    the read but there are no special freshness guarantees, i.e., we may verify
    the preconditions against a state, and return a state, that was already
    arbitrarily stale when the request was made.

    If patches are requested and applied, then the preconditions are guarranteed
    to have been valid when the patch was applied and the returned home screen image
    was accurate at some point during the request, though the new state of the
    home screen image may be stale by the time it is received by the client.

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        conn = await itgs.conn()

        preconditions = args.precondition.to_simple()
        patch = args.patch.to_simple()

        patch_queries = do_patch(args.uid, preconditions, patch)
        cursor = conn.cursor("strong" if patch_queries else "none")

        queries = [
            *check_preconditions(args.uid, preconditions),
            *check_subresources(patch),
            *patch_queries,
            do_read(args.uid),
        ]

        response = await cursor.executeunified2(
            [q.sql for q in queries], [q.args for q in queries]
        )

        assert len(response) == len(queries), f"{response=}, {queries=}"

        precondition_errors: List[_PreconditionFailedException] = []
        subresource_errors: List[_SubresourceMissingException] = []
        update_errors: List[_UpdateFailedException] = []

        for query, result in zip(queries, response.items):
            try:
                await query.process_result(result)
            except _PreconditionFailedException as e:
                precondition_errors.append(e)
            except _SubresourceMissingException as e:
                subresource_errors.append(e)
            except _UpdateFailedException as e:
                update_errors.append(e)

        made_changes = patch_queries and not update_errors

        if precondition_errors:
            assert not made_changes, response
            return Response(
                content=StandardErrorResponse[ERROR_412_TYPES](
                    type="precondition_failed",
                    message=(
                        "the precondition was not met:\n- "
                        + "\n- ".join(
                            f"{e.field}: expected {e.expected!r}, but was {e.actual!r}"
                            for e in precondition_errors
                        )
                    ),
                ).model_dump_json(),
                status_code=412,
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        if subresource_errors:
            assert not made_changes, response
            return subresource_errors[0].to_response()

        if update_errors:
            return update_errors[0].to_response()

        read_result = response.items[-1]
        if not read_result.results:
            assert not made_changes, response
            return ERROR_404_RESPONSES["home_screen_image_not_found"]

        home_screen_image = await parse_read_result(itgs, read_result)
        return Response(
            content=home_screen_image.__pydantic_serializer__.to_json(
                home_screen_image
            ),
            status_code=200,
            headers={
                "Content-Type": "application/json; charset=utf-8",
            },
        )


class _PreconditionFailedException(Exception):
    def __init__(self, field: str, expected: str, actual: str):
        super().__init__(f"expected {field!r} to be {expected}, but was {actual}")
        self.field = field
        self.expected = expected
        self.actual = actual


class _SubresourceMissingException(Exception):
    def __init__(self, err_type: ERROR_404_TYPES, field: str, uid: str):
        super().__init__(f"no {field!r} with UID {uid!r}")
        self.err_type: ERROR_404_TYPES = err_type
        self.field = field
        self.uid = uid

    def to_response(self) -> Response:
        return ERROR_404_RESPONSES[self.err_type]


class _UpdateFailedException(Exception):
    def __init__(self) -> None:
        super().__init__("the home screen image could not be updated")

    def to_response(self) -> Response:
        return Response(
            status_code=500,
            content=StandardErrorResponse[Literal["internal_error"]](
                type="internal_error",
                message="the home screen image could not be updated",
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )


@dataclass
class _Query:
    sql: str
    args: list

    process_result: Callable[[ResultItem], Coroutine[None, None, None]]
    """The function to process the result of the query. Should raise
    _PreconditionFailedException, _SubresourceMissingException, 
    or _InsertFailedException if the result is not as expected.
    """


def _check_simple_precondition(uid: str, field: str, expected: Any) -> List[_Query]:
    if expected is _NotSetEnum.NOT_SET:
        return []

    async def _check(item: ResultItem) -> None:
        if item.results:
            actual = item.results[0][0]
            raise _PreconditionFailedException(field, str(expected), str(actual))

    return [
        _Query(
            f"SELECT {field} FROM home_screen_images WHERE uid=? AND "
            + (f"{field} IS NOT NULL" if expected is None else f"{field} <> ?"),
            [uid, *([] if expected is None else [expected])],
            _check,
        )
    ]


def _check_joined_precondition(
    uid: str, table: str, join_field: str, field: str, expected: Any
) -> List[_Query]:
    if expected is _NotSetEnum.NOT_SET:
        return []

    async def _check(item: ResultItem) -> None:
        if item.results:
            actual = item.results[0][0]
            raise _PreconditionFailedException(
                f"{join_field} -> {table}.id [{field}]", str(expected), str(actual)
            )

    if expected is None:
        return [
            _Query(
                f"SELECT {table}.{field} FROM home_screen_images JOIN {table} ON {table}.id = home_screen_images.{join_field} WHERE home_screen_images.uid=? AND {table}.{field} IS NOT NULL",
                [uid],
                _check,
            )
        ]

    return [
        _Query(
            f"SELECT {table}.{field} FROM home_screen_images JOIN {table} ON {table}.id = home_screen_images.{join_field} WHERE home_screen_images.uid=? AND {table}.{field} <> ?",
            [uid, expected],
            _check,
        )
    ]


def check_preconditions(
    uid: str, preconditions: HomeScreenImagePreconditionSimple
) -> List[_Query]:
    return [
        *_check_simple_precondition(uid, "start_time", preconditions.start_time),
        *_check_simple_precondition(uid, "end_time", preconditions.end_time),
        *_check_simple_precondition(uid, "flags", preconditions.flags),
        *_check_simple_precondition(
            uid,
            "dates",
            (
                (
                    None
                    if preconditions.dates is None
                    else json.dumps(preconditions.dates, separators=(",", ":"))
                )
                if preconditions.dates is not _NotSetEnum.NOT_SET
                else _NotSetEnum.NOT_SET
            ),
        ),
        *_check_simple_precondition(uid, "created_at", preconditions.created_at),
        *_check_simple_precondition(uid, "live_at", preconditions.live_at),
        *_check_joined_precondition(
            uid,
            "image_files",
            "image_file_id",
            "uid",
            preconditions.image_file_uid,
        ),
        *_check_joined_precondition(
            uid,
            "image_files",
            "darkened_image_file_id",
            "uid",
            preconditions.darkened_image_file_uid,
        ),
    ]


def check_subresources(patch: HomeScreenImagePatchSimple) -> List[_Query]:
    return []


def _checked_home_screen_images(
    uid: str,
    patch: HomeScreenImagePatchSimple,
    precondition: HomeScreenImagePreconditionSimple,
    qargs: list,
) -> str:
    """Returns an expression like

    checked_home_screen_images(id, uid) AS (...)

    which will be populated with 0 or 1 rows, depending on whether the
    home screen image meets the preconditions

    Args:
        uid (str): the uid of the home screen image; if a row is populated in
            checked_home_screen_images, it will be this uid
        patch (HomeScreenImagePatchSimple): the patch to apply
        precondition (HomeScreenImagePreconditionSimple): the precondition to check
        qargs (list): the list of arguments to the query
    """

    result = io.StringIO()
    result.write(
        "checked_home_screen_images(id, uid) AS (SELECT home_screen_images.id, home_screen_images.uid FROM home_screen_images"
    )

    if precondition.image_file_uid is not _NotSetEnum.NOT_SET:
        result.write(
            " JOIN image_files ON image_files.id = home_screen_images.image_file_id"
        )

    if precondition.darkened_image_file_uid is not _NotSetEnum.NOT_SET:
        result.write(
            " JOIN image_files AS darkened_image_files "
            "ON darkened_image_files.id = home_screen_images.darkened_image_file_id"
        )

    result.write(" WHERE home_screen_images.uid = ?")
    qargs.append(uid)

    if precondition.image_file_uid is not _NotSetEnum.NOT_SET:
        if precondition.image_file_uid is None:
            result.write(" AND image_files.id IS NULL")
        else:
            result.write(" AND image_files.uid = ?")
            qargs.append(precondition.image_file_uid)

    if precondition.darkened_image_file_uid is not _NotSetEnum.NOT_SET:
        if precondition.darkened_image_file_uid is None:
            result.write(" AND darkened_image_files.id IS NULL")
        else:
            result.write(" AND darkened_image_files.uid = ?")
            qargs.append(precondition.darkened_image_file_uid)

    if precondition.start_time is not _NotSetEnum.NOT_SET:
        result.write(" AND home_screen_images.start_time = ?")
        qargs.append(precondition.start_time)

    if precondition.end_time is not _NotSetEnum.NOT_SET:
        result.write(" AND home_screen_images.end_time = ?")
        qargs.append(precondition.end_time)

    if precondition.flags is not _NotSetEnum.NOT_SET:
        result.write(" AND home_screen_images.flags = ?")
        qargs.append(precondition.flags)

    if precondition.dates is not _NotSetEnum.NOT_SET:
        if precondition.dates is None:
            result.write(" AND home_screen_images.dates IS NULL")
        else:
            result.write(" AND home_screen_images.dates = ?")
            qargs.append(json.dumps(precondition.dates, separators=(",", ":")))

    if precondition.live_at is not _NotSetEnum.NOT_SET:
        result.write(" AND home_screen_images.live_at = ?")
        qargs.append(precondition.live_at)

    if precondition.created_at is not _NotSetEnum.NOT_SET:
        result.write(" AND home_screen_images.created_at = ?")
        qargs.append(precondition.created_at)

    result.write(")")
    return result.getvalue()


def do_patch(
    uid: str,
    preconditions: HomeScreenImagePreconditionSimple,
    patch: HomeScreenImagePatchSimple,
) -> List[_Query]:
    updates: List[str] = []
    update_qargs: List[Any] = []

    if patch.start_time is not _NotSetEnum.NOT_SET:
        updates.append("start_time = ?")
        update_qargs.append(patch.start_time)

    if patch.end_time is not _NotSetEnum.NOT_SET:
        updates.append("end_time = ?")
        update_qargs.append(patch.end_time)

    if patch.flags is not _NotSetEnum.NOT_SET:
        updates.append("flags = ?")
        update_qargs.append(patch.flags)

    if patch.dates is not _NotSetEnum.NOT_SET:
        if patch.dates is None:
            updates.append("dates = NULL")
        else:
            updates.append("dates = ?")
            update_qargs.append(
                json.dumps(patch.dates, separators=(",", ":"), sort_keys=True)
            )

    if patch.live_at is not _NotSetEnum.NOT_SET:
        updates.append("live_at = ?")
        update_qargs.append(patch.live_at)

    if not updates:
        return []

    update_sql = ", ".join(updates)

    query = io.StringIO()
    qargs = []

    query.write("WITH ")
    query.write(_checked_home_screen_images(uid, patch, preconditions, qargs))
    query.write(" UPDATE home_screen_images SET ")
    query.write(update_sql)
    qargs.extend(update_qargs)
    query.write(
        " FROM checked_home_screen_images WHERE home_screen_images.id = checked_home_screen_images.id"
    )

    async def _check(r: ResultItem) -> None:
        if r.rows_affected != 1:
            if r.rows_affected is not None and r.rows_affected > 0:
                await handle_warning(
                    f"{__name__}:multiple_rows_affected",
                    f"expected to update 0 or 1 rows, but updated {r.rows_affected}",
                    is_urgent=True,
                )
            raise _UpdateFailedException()

    return [_Query(query.getvalue(), qargs, _check)]


def do_read(uid: str) -> _Query:
    async def _check(r: ResultItem) -> None:
        if not r.results:
            raise _SubresourceMissingException(
                "home_screen_image_not_found", "home_screen_image", uid
            )

    return _Query(
        sql=f"""
{STANDARD_INTERNAL_HOME_SCREEN_IMAGE_ROW_SELECT_JOIN}
WHERE
    home_screen_images.uid = ?
        """,
        args=[uid],
        process_result=_check,
    )


async def parse_read_result(itgs: Itgs, r: ResultItem) -> InternalHomeScreenImage:
    assert r.results

    row = r.results[0]
    return await parse_internal_home_screen_image_row(
        itgs, row=InternalHomeScreenImageRow(*row)
    )
