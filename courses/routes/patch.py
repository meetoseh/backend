import io
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import (
    Annotated,
    Any,
    Callable,
    Coroutine,
    Dict,
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
from content_files.models import ContentFileRef
from error_middleware import handle_warning
from image_files.models import ImageFileRef
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from itgs import Itgs
from courses.models.internal_course import InternalCourse, InternalCourseInstructor
from dataclasses import dataclass
from enum import Enum
from functools import partial
import image_files.auth as image_files_auth
import content_files.auth as content_files_auth

router = APIRouter()


class _NotSetEnum(Enum):
    NOT_SET = "NOT_SET"


_NotSet = Literal[_NotSetEnum.NOT_SET]


@dataclass
class CoursePreconditionSimple:
    slug: Union[str, _NotSet]
    flags: Union[int, _NotSet]
    revenue_cat_entitlement: Union[str, _NotSet]
    title: Union[str, _NotSet]
    description: Union[str, _NotSet]
    instructor_uid: Union[str, _NotSet]
    background_original_image_uid: Union[str, None, _NotSet]
    background_darkened_image_uid: Union[str, None, _NotSet]
    video_content_uid: Union[str, None, _NotSet]
    video_thumbnail_uid: Union[str, None, _NotSet]
    logo_image_uid: Union[str, None, _NotSet]
    hero_image_uid: Union[str, None, _NotSet]


class CoursePreconditionModel(BaseModel):
    slug: str = Field(default_factory=lambda: _NotSetEnum.NOT_SET)
    flags: int = Field(default_factory=lambda: _NotSetEnum.NOT_SET)
    revenue_cat_entitlement: str = Field(default_factory=lambda: _NotSetEnum.NOT_SET)
    title: str = Field(default_factory=lambda: _NotSetEnum.NOT_SET)
    description: str = Field(default_factory=lambda: _NotSetEnum.NOT_SET)
    instructor_uid: str = Field(default_factory=lambda: _NotSetEnum.NOT_SET)
    background_original_image_uid: Optional[str] = Field(None)
    background_darkened_image_uid: Optional[str] = Field(None)
    video_content_uid: Optional[str] = Field(None)
    video_thumbnail_uid: Optional[str] = Field(None)
    logo_image_uid: Optional[str] = Field(None)
    hero_image_uid: Optional[str] = Field(None)

    def to_simple(self) -> CoursePreconditionSimple:
        dumped = self.model_dump(exclude_unset=True)
        return CoursePreconditionSimple(
            slug=dumped.get("slug", _NotSetEnum.NOT_SET),
            flags=dumped.get("flags", _NotSetEnum.NOT_SET),
            revenue_cat_entitlement=dumped.get(
                "revenue_cat_entitlement", _NotSetEnum.NOT_SET
            ),
            title=dumped.get("title", _NotSetEnum.NOT_SET),
            description=dumped.get("description", _NotSetEnum.NOT_SET),
            instructor_uid=dumped.get("instructor_uid", _NotSetEnum.NOT_SET),
            background_original_image_uid=dumped.get(
                "background_original_image_uid", _NotSetEnum.NOT_SET
            ),
            background_darkened_image_uid=dumped.get(
                "background_darkened_image_uid", _NotSetEnum.NOT_SET
            ),
            video_content_uid=dumped.get("video_content_uid", _NotSetEnum.NOT_SET),
            video_thumbnail_uid=dumped.get("video_thumbnail_uid", _NotSetEnum.NOT_SET),
            logo_image_uid=dumped.get("logo_image_uid", _NotSetEnum.NOT_SET),
            hero_image_uid=dumped.get("hero_image_uid", _NotSetEnum.NOT_SET),
        )


@dataclass
class CoursePatchSimple:
    slug: Union[str, _NotSet]
    flags: Union[int, _NotSet]
    revenue_cat_entitlement: Union[str, _NotSet]
    title: Union[str, _NotSet]
    description: Union[str, _NotSet]
    instructor_uid: Union[str, _NotSet]
    background_image_uid: Union[str, _NotSet]
    video_content_uid: Union[str, _NotSet]
    video_thumbnail_uid: Union[str, _NotSet]
    logo_image_uid: Union[str, _NotSet]
    hero_image_uid: Union[str, _NotSet]


class CoursePatchModel(BaseModel):
    slug: str = Field(default_factory=lambda: _NotSetEnum.NOT_SET)
    flags: int = Field(default_factory=lambda: _NotSetEnum.NOT_SET)
    revenue_cat_entitlement: str = Field(default_factory=lambda: _NotSetEnum.NOT_SET)
    title: str = Field(default_factory=lambda: _NotSetEnum.NOT_SET)
    description: str = Field(default_factory=lambda: _NotSetEnum.NOT_SET)
    instructor_uid: str = Field(default_factory=lambda: _NotSetEnum.NOT_SET)
    background_image_uid: str = Field(default_factory=lambda: _NotSetEnum.NOT_SET)
    video_content_uid: str = Field(default_factory=lambda: _NotSetEnum.NOT_SET)
    video_thumbnail_uid: str = Field(default_factory=lambda: _NotSetEnum.NOT_SET)
    logo_image_uid: str = Field(default_factory=lambda: _NotSetEnum.NOT_SET)
    hero_image_uid: str = Field(default_factory=lambda: _NotSetEnum.NOT_SET)

    def to_simple(self) -> CoursePatchSimple:
        dumped = self.model_dump(exclude_unset=True)
        return CoursePatchSimple(
            slug=dumped.get("slug", _NotSetEnum.NOT_SET),
            flags=dumped.get("flags", _NotSetEnum.NOT_SET),
            revenue_cat_entitlement=dumped.get(
                "revenue_cat_entitlement", _NotSetEnum.NOT_SET
            ),
            title=dumped.get("title", _NotSetEnum.NOT_SET),
            description=dumped.get("description", _NotSetEnum.NOT_SET),
            instructor_uid=dumped.get("instructor_uid", _NotSetEnum.NOT_SET),
            background_image_uid=dumped.get(
                "background_image_uid", _NotSetEnum.NOT_SET
            ),
            video_content_uid=dumped.get("video_content_uid", _NotSetEnum.NOT_SET),
            video_thumbnail_uid=dumped.get("video_thumbnail_uid", _NotSetEnum.NOT_SET),
            logo_image_uid=dumped.get("logo_image_uid", _NotSetEnum.NOT_SET),
            hero_image_uid=dumped.get("hero_image_uid", _NotSetEnum.NOT_SET),
        )


class PatchCourseRequest(BaseModel):
    uid: str = Field(description="The uid of the course to update")
    precondition: CoursePreconditionModel = Field(
        default_factory=lambda: CoursePreconditionModel.model_validate({}),
        description=(
            "The precondition for the update. The update will only go through "
            "if for each explicitly set field in the precondition, the current "
            "value of the field in the course being updated matches the value "
            "set in the precondition.\n\n"
            "Explicitly setting null in the precondition "
            "will require the field is null in the course being updated, whereas "
            "omitting a key in the precondition will allow any value in the course "
            "being updated.\n\n"
            "Be aware the precondition is specifying image file uids and content file "
            "uids, not, e.g., course_hero_images uids or course_videos uids."
        ),
    )
    patch: CoursePatchModel = Field(
        default_factory=lambda: CoursePatchModel.model_validate({}),
        description=(
            "The patch to apply to the course. Any explicitly set field in the "
            "patch will be applied to the course being updated, provided the "
            "precondition is met.\n\n"
            "Be aware the patch is specifying course <-> image file relationship uids "
            "and course <-> content file relationship uids, not image file uids "
            "directly, to ensure that the indicated file has been appropriately "
            "processed for the required usecase."
        ),
    )


ERROR_404_TYPES = Literal[
    "course_not_found",
    "instructor_not_found",
    "background_not_found",
    "video_not_found",
    "video_thumbnail_not_found",
    "logo_not_found",
    "hero_not_found",
]
ERROR_409_TYPES = Literal["course_slug_exists"]
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
    "course_slug_exists": Response(
        status_code=409,
        content=StandardErrorResponse[ERROR_409_TYPES](
            type="course_slug_exists",
            message="the slug cannot be changed to the indicated one as another course already has the new slug",
        ).model_dump_json(),
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
}

# precondition_failed is generated on the fly to include the fields that failed


@router.patch(
    "/",
    response_model=InternalCourse,
    responses={
        "404": {
            "description": "the course does not exist or one of the subresources in the patch do not exist",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        "409": {
            "description": "the new values in the patch would conflict with an existing course",
            "model": StandardErrorResponse[ERROR_409_TYPES],
        },
        "412": {
            "description": "the precondition was not met",
            "model": StandardErrorResponse[ERROR_412_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def patch_course(
    args: PatchCourseRequest, authorization: Annotated[Optional[str], Header()] = None
):
    """Patches the course with the given UID, optionally restricted by the
    given precondition.

    If no patches are requested, the preconditions are checked atomically with
    the read but there are no special freshness guarantees, i.e., we may verify
    the preconditions against a state, and return a state, that was already
    arbitrarily stale when the request was made.

    If patches are requested and applied, then the preconditions are guarranteed
    to have been valid when the patch was applied and the returned course was
    accurate at some point during the request, though the new state of the
    course may be stale by the time it is received by the client.

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
            *check_conflicts(args.uid, patch),
            *patch_queries,
            do_read(args.uid),
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
            return ERROR_404_RESPONSES["course_not_found"]

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
            f"{field!r} is already in use by another course: {other_uid!r}"
        )
        self.err_type: ERROR_409_TYPES = err_type
        self.field = field
        self.other_uid = other_uid

    def to_response(self) -> Response:
        return ERROR_409_RESPONSES[self.err_type]


class _UpdateFailedException(Exception):
    def __init__(self) -> None:
        super().__init__("the course could not be updated")

    def to_response(self) -> Response:
        return Response(
            status_code=500,
            content=StandardErrorResponse[Literal["internal_error"]](
                type="internal_error",
                message="the course could not be updated",
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
            f"SELECT {field} FROM courses WHERE uid=? AND "
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
                f"SELECT {table}.{field} FROM courses JOIN {table} ON {table}.id = courses.{join_field} WHERE courses.uid=? AND {table}.{field} IS NOT NULL",
                [uid],
                _check,
            )
        ]

    return [
        _Query(
            f"SELECT {table}.{field} FROM courses JOIN {table} ON {table}.id = courses.{join_field} WHERE courses.uid=? AND {table}.{field} <> ?",
            [uid, expected],
            _check,
        )
    ]


def check_preconditions(
    uid: str, preconditions: CoursePreconditionSimple
) -> List[_Query]:
    return [
        *_check_simple_precondition(uid, "slug", preconditions.slug),
        *_check_simple_precondition(uid, "flags", preconditions.flags),
        *_check_simple_precondition(
            uid, "revenue_cat_entitlement", preconditions.revenue_cat_entitlement
        ),
        *_check_simple_precondition(uid, "title", preconditions.title),
        *_check_simple_precondition(uid, "description", preconditions.description),
        *_check_joined_precondition(
            uid, "instructors", "instructor_id", "uid", preconditions.instructor_uid
        ),
        *_check_joined_precondition(
            uid,
            "image_files",
            "background_original_image_file_id",
            "uid",
            preconditions.background_original_image_uid,
        ),
        *_check_joined_precondition(
            uid,
            "image_files",
            "background_darkened_image_file_id",
            "uid",
            preconditions.background_darkened_image_uid,
        ),
        *_check_joined_precondition(
            uid,
            "content_files",
            "video_content_file_id",
            "uid",
            preconditions.video_content_uid,
        ),
        *_check_joined_precondition(
            uid,
            "image_files",
            "video_thumbnail_image_file_id",
            "uid",
            preconditions.video_thumbnail_uid,
        ),
        *_check_joined_precondition(
            uid,
            "image_files",
            "logo_image_file_id",
            "uid",
            preconditions.logo_image_uid,
        ),
        *_check_joined_precondition(
            uid,
            "image_files",
            "hero_image_file_id",
            "uid",
            preconditions.hero_image_uid,
        ),
    ]


def check_subresources(patch: CoursePatchSimple) -> List[_Query]:
    async def _check(
        err_type: ERROR_404_TYPES, field: str, uid: str, r: ResultItem
    ) -> None:
        if not r.results:
            raise _SubresourceMissingException(err_type, field, uid)

    result: List[_Query] = []

    if patch.instructor_uid is not _NotSetEnum.NOT_SET:
        result.append(
            _Query(
                "SELECT 1 FROM instructors WHERE uid=?",
                [patch.instructor_uid],
                partial(
                    _check, "instructor_not_found", "instructor", patch.instructor_uid
                ),
            )
        )

    if patch.background_image_uid is not _NotSetEnum.NOT_SET:
        result.append(
            _Query(
                "SELECT 1 FROM course_background_images WHERE uid=?",
                [patch.background_image_uid],
                partial(
                    _check,
                    "background_not_found",
                    "background image",
                    patch.background_image_uid,
                ),
            )
        )

    if patch.video_content_uid is not _NotSetEnum.NOT_SET:
        result.append(
            _Query(
                "SELECT 1 FROM course_videos WHERE uid=?",
                [patch.video_content_uid],
                partial(
                    _check, "video_not_found", "video content", patch.video_content_uid
                ),
            )
        )

    if patch.video_thumbnail_uid is not _NotSetEnum.NOT_SET:
        result.append(
            _Query(
                "SELECT 1 FROM course_video_thumbnail_images WHERE uid=?",
                [patch.video_thumbnail_uid],
                partial(
                    _check,
                    "video_thumbnail_not_found",
                    "video thumbnail",
                    patch.video_thumbnail_uid,
                ),
            )
        )

    if patch.logo_image_uid is not _NotSetEnum.NOT_SET:
        result.append(
            _Query(
                "SELECT 1 FROM course_logo_images WHERE uid=?",
                [patch.logo_image_uid],
                partial(_check, "logo_not_found", "logo image", patch.logo_image_uid),
            )
        )

    if patch.hero_image_uid is not _NotSetEnum.NOT_SET:
        result.append(
            _Query(
                "SELECT 1 FROM course_hero_images WHERE uid=?",
                [patch.hero_image_uid],
                partial(_check, "hero_not_found", "hero image", patch.hero_image_uid),
            )
        )

    return result


def check_conflicts(uid: str, patch: CoursePatchSimple) -> List[_Query]:
    if patch.slug is _NotSetEnum.NOT_SET:
        return []

    async def _check(r: ResultItem) -> None:
        if r.results:
            raise _ConflictException("course_slug_exists", "slug", r.results[0][0])

    return [
        _Query(
            "SELECT slug FROM courses WHERE slug = ? AND uid <> ?",
            [patch.slug, uid],
            _check,
        )
    ]


def _checked_courses(
    uid: str,
    patch: CoursePatchSimple,
    precondition: CoursePreconditionSimple,
    qargs: list,
) -> str:
    """Returns an expression like

    checked_courses(id, uid) AS (...)

    which will be populated with 0 or 1 rows, depending on whether the
    course meets the preconditions AND all of the subresources required
    for the patch exist.

    Args:
        uid (str): the uid of the course; if a row is populated in checked_courses,
            it will be this uid
        patch (CoursePatchSimple): the patch to apply
        precondition (CoursePreconditionSimple): the precondition to check
        qargs (list): the list of arguments to the query
    """

    result = io.StringIO()
    result.write(
        "checked_courses(id, uid) AS (SELECT courses.id, courses.uid FROM courses"
    )

    if precondition.instructor_uid is not _NotSetEnum.NOT_SET:
        result.write(" JOIN instructors ON instructors.id = courses.instructor_id")

    if precondition.background_original_image_uid is not _NotSetEnum.NOT_SET:
        result.write(
            " LEFT OUTER JOIN image_files AS background_original_images "
            "ON background_original_images.id = courses.background_original_image_file_id"
        )

    if precondition.background_darkened_image_uid is not _NotSetEnum.NOT_SET:
        result.write(
            " LEFT OUTER JOIN image_files AS background_darkened_images "
            "ON background_darkened_images.id = courses.background_darkened_image_file_id"
        )

    if precondition.video_content_uid is not _NotSetEnum.NOT_SET:
        result.write(
            " LEFT OUTER JOIN content_files AS video_contents "
            "ON video_contents.id = courses.video_content_file_id"
        )

    if precondition.video_thumbnail_uid is not _NotSetEnum.NOT_SET:
        result.write(
            " LEFT OUTER JOIN image_files AS video_thumbnails "
            "ON video_thumbnails.id = courses.video_thumbnail_image_file_id"
        )

    if precondition.logo_image_uid is not _NotSetEnum.NOT_SET:
        result.write(
            " LEFT OUTER JOIN image_files AS logos "
            "ON logos.id = courses.logo_image_file_id"
        )

    if precondition.hero_image_uid is not _NotSetEnum.NOT_SET:
        result.write(
            " LEFT OUTER JOIN image_files AS hero_images "
            "ON hero_images.id = courses.hero_image_file_id"
        )

    result.write(" WHERE courses.uid = ?")
    qargs.append(uid)

    if precondition.slug is not _NotSetEnum.NOT_SET:
        result.write(" AND courses.slug = ?")
        qargs.append(precondition.slug)

    if precondition.flags is not _NotSetEnum.NOT_SET:
        result.write(" AND courses.flags = ?")
        qargs.append(precondition.flags)

    if precondition.revenue_cat_entitlement is not _NotSetEnum.NOT_SET:
        result.write(" AND courses.revenue_cat_entitlement = ?")
        qargs.append(precondition.revenue_cat_entitlement)

    if precondition.title is not _NotSetEnum.NOT_SET:
        result.write(" AND courses.title = ?")
        qargs.append(precondition.title)

    if precondition.description is not _NotSetEnum.NOT_SET:
        result.write(" AND courses.description = ?")
        qargs.append(precondition.description)

    if precondition.instructor_uid is not _NotSetEnum.NOT_SET:
        result.write(" AND instructors.uid = ?")
        qargs.append(precondition.instructor_uid)

    if precondition.background_original_image_uid is not _NotSetEnum.NOT_SET:
        if precondition.background_original_image_uid is None:
            result.write(" AND background_original_images.id IS NULL")
        else:
            result.write(" AND background_original_images.uid = ?")
            qargs.append(precondition.background_original_image_uid)

    if precondition.background_darkened_image_uid is not _NotSetEnum.NOT_SET:
        if precondition.background_darkened_image_uid is None:
            result.write(" AND background_darkened_images.id IS NULL")
        else:
            result.write(" AND background_darkened_images.uid = ?")
            qargs.append(precondition.background_darkened_image_uid)

    if precondition.video_content_uid is not _NotSetEnum.NOT_SET:
        if precondition.video_content_uid is None:
            result.write(" AND video_contents.id IS NULL")
        else:
            result.write(" AND video_contents.uid = ?")
            qargs.append(precondition.video_content_uid)

    if precondition.video_thumbnail_uid is not _NotSetEnum.NOT_SET:
        if precondition.video_thumbnail_uid is None:
            result.write(" AND video_thumbnails.id IS NULL")
        else:
            result.write(" AND video_thumbnails.uid = ?")
            qargs.append(precondition.video_thumbnail_uid)

    if precondition.logo_image_uid is not _NotSetEnum.NOT_SET:
        if precondition.logo_image_uid is None:
            result.write(" AND logos.id IS NULL")
        else:
            result.write(" AND logos.uid = ?")
            qargs.append(precondition.logo_image_uid)

    if precondition.hero_image_uid is not _NotSetEnum.NOT_SET:
        if precondition.hero_image_uid is None:
            result.write(" AND hero_images.id IS NULL")
        else:
            result.write(" AND hero_images.uid = ?")
            qargs.append(precondition.hero_image_uid)

    if patch.slug is not _NotSetEnum.NOT_SET:
        result.write(" AND NOT EXISTS (SELECT 1 FROM courses AS c2 WHERE c2.slug = ?)")
        qargs.append(patch.slug)

    if patch.background_image_uid is not _NotSetEnum.NOT_SET:
        result.write(
            " AND EXISTS (SELECT 1 FROM course_background_images WHERE course_background_images.uid = ?)"
        )
        qargs.append(patch.background_image_uid)

    if patch.video_content_uid is not _NotSetEnum.NOT_SET:
        result.write(
            " AND EXISTS (SELECT 1 FROM course_videos WHERE course_videos.uid = ?)"
        )
        qargs.append(patch.video_content_uid)

    if patch.video_thumbnail_uid is not _NotSetEnum.NOT_SET:
        result.write(
            " AND EXISTS (SELECT 1 FROM course_video_thumbnail_images WHERE course_video_thumbnail_images.uid = ?)"
        )
        qargs.append(patch.video_thumbnail_uid)

    if patch.logo_image_uid is not _NotSetEnum.NOT_SET:
        result.write(
            " AND EXISTS (SELECT 1 FROM course_logo_images WHERE course_logo_images.uid = ?)"
        )
        qargs.append(patch.logo_image_uid)

    if patch.hero_image_uid is not _NotSetEnum.NOT_SET:
        result.write(
            " AND EXISTS (SELECT 1 FROM course_hero_images WHERE course_hero_images.uid = ?)"
        )
        qargs.append(patch.hero_image_uid)

    result.write(")")
    return result.getvalue()


def do_patch(
    uid: str, preconditions: CoursePreconditionSimple, patch: CoursePatchSimple
) -> List[_Query]:
    updates: List[str] = []
    update_qargs: List[Any] = []

    if patch.slug is not _NotSetEnum.NOT_SET:
        updates.append("slug = ?")
        update_qargs.append(patch.slug)

    if patch.flags is not _NotSetEnum.NOT_SET:
        updates.append("flags = ?")
        update_qargs.append(patch.flags)

    if patch.revenue_cat_entitlement is not _NotSetEnum.NOT_SET:
        updates.append("revenue_cat_entitlement = ?")
        update_qargs.append(patch.revenue_cat_entitlement)

    if patch.title is not _NotSetEnum.NOT_SET:
        updates.append("title = ?")
        update_qargs.append(patch.title)

    if patch.description is not _NotSetEnum.NOT_SET:
        updates.append("description = ?")
        update_qargs.append(patch.description)

    if patch.instructor_uid is not _NotSetEnum.NOT_SET:
        updates.append(
            "instructor_id = (SELECT instructors.id FROM instructors WHERE instructors.uid = ?)"
        )
        update_qargs.append(patch.instructor_uid)

    if patch.background_image_uid is not _NotSetEnum.NOT_SET:
        updates.append(
            "background_original_image_file_id = (SELECT course_background_images.original_image_file_id FROM course_background_images WHERE course_background_images.uid = ?)"
        )
        update_qargs.append(patch.background_image_uid)

        updates.append(
            "background_darkened_image_file_id = (SELECT course_background_images.darkened_image_file_id FROM course_background_images WHERE course_background_images.uid = ?)"
        )
        update_qargs.append(patch.background_image_uid)

    if patch.video_content_uid is not _NotSetEnum.NOT_SET:
        updates.append(
            "video_content_file_id = (SELECT course_videos.content_file_id FROM course_videos WHERE course_videos.uid = ?)"
        )
        update_qargs.append(patch.video_content_uid)

    if patch.video_thumbnail_uid is not _NotSetEnum.NOT_SET:
        updates.append(
            "video_thumbnail_image_file_id = (SELECT course_video_thumbnail_images.image_file_id FROM course_video_thumbnail_images WHERE course_video_thumbnail_images.uid = ?)"
        )
        update_qargs.append(patch.video_thumbnail_uid)

    if patch.logo_image_uid is not _NotSetEnum.NOT_SET:
        updates.append(
            "logo_image_file_id = (SELECT course_logo_images.image_file_id FROM course_logo_images WHERE course_logo_images.uid = ?)"
        )
        update_qargs.append(patch.logo_image_uid)

    if patch.hero_image_uid is not _NotSetEnum.NOT_SET:
        updates.append(
            "hero_image_file_id = (SELECT course_hero_images.image_file_id FROM course_hero_images WHERE course_hero_images.uid = ?)"
        )
        update_qargs.append(patch.hero_image_uid)

    if not updates:
        return []

    update_sql = ", ".join(updates)

    query = io.StringIO()
    qargs = []

    query.write("WITH ")
    query.write(_checked_courses(uid, patch, preconditions, qargs))
    query.write(" UPDATE courses SET ")
    query.write(update_sql)
    qargs.extend(update_qargs)
    query.write(" FROM checked_courses WHERE courses.id = checked_courses.id")

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
            raise _SubresourceMissingException("course_not_found", "course", uid)

    return _Query(
        sql="""
SELECT
    courses.uid,
    courses.slug,
    courses.flags,
    courses.revenue_cat_entitlement,
    courses.title,
    courses.description,
    instructors.uid,
    instructors.name,
    instructor_pictures.uid,
    background_original_images.uid,
    background_darkened_images.uid,
    video_contents.uid,
    video_thumbnails.uid,
    logo_images.uid,
    hero_images.uid,
    courses.created_at
FROM courses
JOIN instructors ON instructors.id = courses.instructor_id
LEFT OUTER JOIN image_files AS instructor_pictures
    ON instructor_pictures.id = instructors.picture_image_file_id
LEFT OUTER JOIN image_files AS background_original_images
    ON background_original_images.id = courses.background_original_image_file_id
LEFT OUTER JOIN image_files AS background_darkened_images
    ON background_darkened_images.id = courses.background_darkened_image_file_id
LEFT OUTER JOIN content_files AS video_contents
    ON video_contents.id = courses.video_content_file_id
LEFT OUTER JOIN image_files AS video_thumbnails
    ON video_thumbnails.id = courses.video_thumbnail_image_file_id
LEFT OUTER JOIN image_files AS logo_images
    ON logo_images.id = courses.logo_image_file_id
LEFT OUTER JOIN image_files AS hero_images
    ON hero_images.id = courses.hero_image_file_id
WHERE
    courses.uid = ?
        """,
        args=[uid],
        process_result=_check,
    )


async def parse_read_result(itgs: Itgs, r: ResultItem) -> InternalCourse:
    assert r.results

    row = r.results[0]
    return InternalCourse(
        uid=row[0],
        slug=row[1],
        flags=row[2],
        revenue_cat_entitlement=row[3],
        title=row[4],
        description=row[5],
        instructor=InternalCourseInstructor(
            uid=row[6],
            name=row[7],
            picture=(
                None
                if row[8] is None
                else ImageFileRef(
                    uid=row[8], jwt=await image_files_auth.create_jwt(itgs, row[8])
                )
            ),
        ),
        background_original_image=(
            None
            if row[9] is None
            else ImageFileRef(
                uid=row[9], jwt=await image_files_auth.create_jwt(itgs, row[9])
            )
        ),
        background_darkened_image=(
            None
            if row[10] is None
            else ImageFileRef(
                uid=row[10], jwt=await image_files_auth.create_jwt(itgs, row[10])
            )
        ),
        video_content=(
            None
            if row[11] is None
            else ContentFileRef(
                uid=row[11], jwt=await content_files_auth.create_jwt(itgs, row[11])
            )
        ),
        video_thumbnail=(
            None
            if row[12] is None
            else ImageFileRef(
                uid=row[12], jwt=await image_files_auth.create_jwt(itgs, row[12])
            )
        ),
        logo_image=(
            None
            if row[13] is None
            else ImageFileRef(
                uid=row[13], jwt=await image_files_auth.create_jwt(itgs, row[13])
            )
        ),
        hero_image=(
            None
            if row[14] is None
            else ImageFileRef(
                uid=row[14], jwt=await image_files_auth.create_jwt(itgs, row[14])
            )
        ),
        created_at=row[15],
    )
