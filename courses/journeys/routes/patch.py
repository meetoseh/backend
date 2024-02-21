from functools import partial
import io
from aiohttp_retry import Dict
from fastapi import APIRouter, Header
from fastapi.responses import Response
from typing import (
    Annotated,
    Any,
    Callable,
    Coroutine,
    Iterable,
    List,
    Literal,
    Optional,
    Union,
    cast,
    get_args,
)
from pydantic import BaseModel, Field
from courses.journeys.models.internal_course_journey import (
    InternalCourseJourney,
    create_read_select,
    parse_read_result as parse_course_journey_result,
)
from error_middleware import handle_warning
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from auth import auth_admin
from dataclasses import dataclass
from itgs import Itgs
from enum import Enum
from rqdb.result import ResultItem


class _NotSetEnum(Enum):
    NOT_SET = "NOT_SET"


_NotSet = Literal[_NotSetEnum.NOT_SET]

router = APIRouter()


@dataclass
class CourseJourneyPatchSimple:
    journey_uid: Union[str, _NotSet]
    priority: Union[int, _NotSet]


class CourseJourneyPatch(BaseModel):
    journey_uid: str = Field(
        default_factory=lambda: _NotSetEnum.NOT_SET,
        description="The journey for this association",
    )
    priority: int = Field(
        default_factory=lambda: _NotSetEnum.NOT_SET,
        description="The priority for this association",
    )

    def to_simple(self) -> CourseJourneyPatchSimple:
        dumped = self.model_dump(exclude_unset=True)
        return CourseJourneyPatchSimple(
            journey_uid=dumped.get("journey_uid", _NotSetEnum.NOT_SET),
            priority=dumped.get("priority", _NotSetEnum.NOT_SET),
        )


@dataclass
class CourseJourneyPreconditionSimple:
    course_uid: Union[str, _NotSet]
    journey_uid: Union[str, _NotSet]
    priority: Union[int, _NotSet]


class CourseJourneyPrecondition(BaseModel):
    course_uid: str = Field(
        default_factory=lambda: _NotSetEnum.NOT_SET,
        description="The course for this association",
    )
    journey_uid: str = Field(
        default_factory=lambda: _NotSetEnum.NOT_SET,
        description="The journey for this association",
    )
    priority: int = Field(
        default_factory=lambda: _NotSetEnum.NOT_SET,
        description="The priority for this association",
    )

    def to_simple(self) -> CourseJourneyPreconditionSimple:
        dumped = self.model_dump(exclude_unset=True)
        return CourseJourneyPreconditionSimple(
            course_uid=dumped.get("course_uid", _NotSetEnum.NOT_SET),
            journey_uid=dumped.get("journey_uid", _NotSetEnum.NOT_SET),
            priority=dumped.get("priority", _NotSetEnum.NOT_SET),
        )


class CourseJourneyPatchRequest(BaseModel):
    association_uid: str = Field(description="The association to patch")
    precondition: CourseJourneyPrecondition = Field(
        default_factory=lambda: CourseJourneyPrecondition.model_validate({}),
        description="If specified, the patch will only be applied if the "
        "association matches these values. Unset fields are ignored",
    )
    patch: CourseJourneyPatch = Field(
        default_factory=lambda: CourseJourneyPatch.model_validate({}),
        description="The patch to apply. Unset fields are ignored",
    )


ERROR_404_TYPES = Literal[
    "association_not_found",
    "journey_not_found",
    "course_not_found",
    "course_journey_not_found",
]
ERROR_409_TYPES = Literal["priority_conflict"]
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

ERROR_409_RESPONSES: Dict[ERROR_409_TYPES, Response] = {
    "priority_conflict": Response(
        status_code=409,
        content=StandardErrorResponse[ERROR_409_TYPES](
            type="priority_conflict",
            message="the specified priority is already in use for this course",
        ).model_dump_json(),
        headers={"Content-Type": "application/json; charset=utf-8"},
    ),
}


@router.patch(
    "/",
    status_code=200,
    response_model=InternalCourseJourney,
    responses={
        "404": {
            "description": "The specified association, journey, or course was not found",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        "409": {
            "description": "The specified priority is already in use for this course",
            "model": StandardErrorResponse[ERROR_409_TYPES],
        },
        "412": {
            "description": "The specified precondition was not met",
            "model": StandardErrorResponse[ERROR_412_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def patch_course_journey(
    args: CourseJourneyPatchRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Patches the course journey with the given association uid. This
    does not immediately cause the course export to be reproduced, thus
    the course may temporarily be in an inconsistent state.

    If no patches are requested, the preconditions are checked atomically with
    the read but there are no special freshness guarantees, i.e., we may verify
    the preconditions against a state, and return a state, that was already
    arbitrarily stale when the request was made.

    If patches are requested and applied, then the preconditions are guarranteed
    to have been valid when the patch was applied and the returned course was
    accurate at some point during the request, though the new state of the
    course journey may be stale by the time it is received by the client.

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        conn = await itgs.conn()

        preconditions = args.precondition.to_simple()
        patch = args.patch.to_simple()

        patch_queries = do_patch(args.association_uid, preconditions, patch)
        cursor = conn.cursor("strong" if patch_queries else "none")

        queries = [
            *check_preconditions(args.association_uid, preconditions),
            *check_subresources(patch),
            *check_conflicts(args.association_uid, patch),
            *patch_queries,
            do_read(args.association_uid),
        ]

        response = await cursor.executeunified2(
            [q.sql for q in queries], [q.args for q in queries]
        )

        assert len(response) == len(queries), f"{response=}, {queries=}"

        precondition_errors: List[_PreconditionFailedException] = []
        subresource_errors: List[_SubresourceMissingException] = []
        conflict_errors: List[_ConflictException] = []
        update_errors: List[_UpdateFailedException] = []

        for query, result in zip(queries, response.items):
            try:
                await query.process_result(result)
            except _PreconditionFailedException as e:
                precondition_errors.append(e)
            except _SubresourceMissingException as e:
                subresource_errors.append(e)
            except _ConflictException as e:
                conflict_errors.append(e)
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

        if conflict_errors:
            assert not made_changes, response
            return conflict_errors[0].to_response()

        if update_errors:
            return update_errors[0].to_response()

        read_result = response.items[-1]
        if not read_result.results:
            assert not made_changes, response
            return ERROR_404_RESPONSES["course_journey_not_found"]

        course = await parse_read_result(itgs, read_result)
        return Response(
            content=course.__pydantic_serializer__.to_json(course),
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


class _ConflictException(Exception):
    def __init__(self, err_type: ERROR_409_TYPES, field: str, other_uid: str):
        super().__init__(
            f"{field!r} is already in use by another course journey: {other_uid!r}"
        )
        self.err_type: ERROR_409_TYPES = err_type
        self.field = field
        self.other_uid = other_uid

    def to_response(self) -> Response:
        return ERROR_409_RESPONSES[self.err_type]


class _UpdateFailedException(Exception):
    def __init__(self) -> None:
        super().__init__("the course journey could not be updated")

    def to_response(self) -> Response:
        return Response(
            status_code=500,
            content=StandardErrorResponse[Literal["internal_error"]](
                type="internal_error",
                message="the course journey could not be updated",
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )


@dataclass
class _Query:
    sql: str
    args: list

    process_result: Callable[[ResultItem], Coroutine[None, None, None]]
    """The function to process the result of the query. Should raise
    _PreconditionFailedException, _SubresourceMissingException, _ConflictException, 
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
            f"SELECT {field} FROM course_journeys WHERE uid=? AND "
            + (f"{field} IS NULL" if expected is None else f"{field} <> ?"),
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
            raise _PreconditionFailedException(field, str(expected), str(actual))

    if expected is None:
        return [
            _Query(
                f"SELECT {table}.{field} FROM course_journeys JOIN {table} ON {table}.id = course_journeys.{join_field} WHERE course_journeys.uid=? AND {table}.{field} IS NOT NULL",
                [uid],
                _check,
            )
        ]

    return [
        _Query(
            f"SELECT {table}.{field} FROM course_journeys JOIN {table} ON {table}.id = course_journeys.{join_field} WHERE course_journeys.uid=? AND {table}.{field} <> ?",
            [uid, expected],
            _check,
        )
    ]


def check_preconditions(
    uid: str, preconditions: CourseJourneyPreconditionSimple
) -> List[_Query]:
    return [
        *_check_joined_precondition(
            uid, "courses", "course_id", "uid", preconditions.course_uid
        ),
        *_check_joined_precondition(
            uid, "journeys", "journey_id", "uid", preconditions.journey_uid
        ),
        *_check_simple_precondition(uid, "priority", preconditions.priority),
    ]


def check_subresources(patch: CourseJourneyPatchSimple) -> List[_Query]:
    async def _check(
        err_type: ERROR_404_TYPES, field: str, uid: str, r: ResultItem
    ) -> None:
        if not r.results:
            raise _SubresourceMissingException(err_type, field, uid)

    result: List[_Query] = []

    if patch.journey_uid is not _NotSetEnum.NOT_SET:
        result.append(
            _Query(
                "SELECT uid FROM journeys WHERE uid=?",
                [patch.journey_uid],
                partial(_check, "journey_not_found", "journey", patch.journey_uid),
            )
        )

    return result


def check_conflicts(uid: str, patch: CourseJourneyPatchSimple) -> List[_Query]:
    if patch.priority is _NotSetEnum.NOT_SET:
        return []

    async def _check(r: ResultItem) -> None:
        if r.results:
            raise _ConflictException(
                "priority_conflict", "priority", str(patch.priority)
            )

    return [
        _Query(
            sql="""
SELECT 1 FROM course_journeys
WHERE
    course_journeys.priority = ?
    AND EXISTS (
        SELECT 1 FROM course_journeys AS cj, courses AS c
        WHERE
            cj.uid = ?
            AND cj.course_id = c.id
            AND course_journeys.course_id = c.id
    )
            """,
            args=[patch.priority, uid],
            process_result=_check,
        )
    ]


def _checked_course_journey(
    uid: str,
    patch: CourseJourneyPatchSimple,
    preconditions: CourseJourneyPreconditionSimple,
    qargs: list,
) -> str:
    """Returns an expression like

    checked_course_journeys(id, uid) AS (...)

    which will be populated with 0 or 1 rows, depending on whether the
    course journey meets the preconditions AND all of the subresources required
    for the patch exist.

    Args:
        uid (str): the uid of the course; if a row is populated in checked_courses,
            it will be this uid
        patch (CourseJourneyPatchSimple): the patch to apply
        precondition (CourseJourneyPreconditionSimple): the precondition to check
        qargs (list): the arguments to the query
    """
    result = io.StringIO()
    result.write(
        "checked_course_journeys(id, uid) AS (SELECT course_journeys.id, course_journeys.uid FROM course_journeys"
    )

    if preconditions.course_uid is not _NotSetEnum.NOT_SET:
        result.write(" JOIN courses ON course_journeys.course_id = courses.id")

    if preconditions.journey_uid is not _NotSetEnum.NOT_SET:
        result.write(" JOIN journeys ON course_journeys.journey_id = journeys.id")

    result.write(" WHERE course_journeys.uid=?")
    qargs.append(uid)

    if preconditions.course_uid is not _NotSetEnum.NOT_SET:
        result.write(" AND courses.uid=?")
        qargs.append(preconditions.course_uid)

    if preconditions.journey_uid is not _NotSetEnum.NOT_SET:
        result.write(" AND journeys.uid=?")
        qargs.append(preconditions.journey_uid)

    if preconditions.priority is not _NotSetEnum.NOT_SET:
        result.write(" AND course_journeys.priority=?")
        qargs.append(preconditions.priority)

    if patch.journey_uid is not _NotSetEnum.NOT_SET:
        result.write(" AND EXISTS (SELECT 1 FROM journeys WHERE uid=?)")
        qargs.append(patch.journey_uid)

    if patch.priority is not _NotSetEnum.NOT_SET:
        result.write(
            " AND NOT EXISTS (SELECT 1 FROM course_journeys AS cj WHERE cj.course_id=course_journeys.course_id AND cj.priority=?)"
        )
        qargs.append(patch.priority)

    result.write(")")
    return result.getvalue()


def do_patch(
    uid: str,
    preconditions: CourseJourneyPreconditionSimple,
    patch: CourseJourneyPatchSimple,
) -> List[_Query]:
    patch_fields = []
    patch_qargs = []
    if patch.journey_uid is not _NotSetEnum.NOT_SET:
        patch_fields.append("journey_id=(SELECT id FROM journeys WHERE uid=?)")
        patch_qargs.append(patch.journey_uid)

    if patch.priority is not _NotSetEnum.NOT_SET:
        patch_fields.append("priority=?")
        patch_qargs.append(patch.priority)

    if not patch_fields:
        return []

    query = io.StringIO()
    query.write("WITH ")
    qargs = []
    query.write(_checked_course_journey(uid, patch, preconditions, qargs))
    query.write(" UPDATE course_journeys SET ")
    query.write(", ".join(patch_fields))
    qargs.extend(patch_qargs)
    query.write(
        " FROM checked_course_journeys WHERE course_journeys.id=checked_course_journeys.id"
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
                "course_journey_not_found", "course_journey", uid
            )

    return _Query(
        sql=create_read_select() + " WHERE course_journeys.uid=?",
        args=[uid],
        process_result=_check,
    )


async def parse_read_result(itgs: Itgs, r: ResultItem) -> InternalCourseJourney:
    parsed = await parse_course_journey_result(itgs, r)
    assert parsed, f"{parsed=}, {r=}"
    return parsed[0]
