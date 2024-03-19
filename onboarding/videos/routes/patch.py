from functools import partial
import io
import json
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Annotated, Any, List, Literal, Optional, cast
from rqdb.result import ResultItem

from auth import auth_admin
from error_middleware import handle_warning
from itgs import Itgs
from models import StandardErrorResponse
from onboarding.videos.lib.internal_onboarding_video import (
    STANDARD_INTERNAL_ONBOARDING_VIDEO_ROW_SELECT_JOIN,
    InternalOnboardingVideo,
    InternalOnboardingVideoRow,
    OnboardingVideoPurpose,
    parse_internal_onboarding_video_row,
)
from resources.patch.docs import (
    PATCH_DOCS,
    PRECONDITION_DOCS,
    create_description,
    create_responses,
)
from resources.patch.exceptions import (
    ConflictException,
    PreconditionFailedException,
    SubresourceMissingException,
    UpdateFailedException,
)
from resources.patch.handle_patch import handle_patch
from resources.patch.not_set import NotSetEnum
from resources.patch.precondition import (
    check_joined_precondition,
    check_simple_precondition,
)
from resources.patch.query import Query


router = APIRouter()


class OnboardingVideoPrecondition(BaseModel):
    purpose: OnboardingVideoPurpose = Field(default_factory=lambda: NotSetEnum.NOT_SET)
    video_content_file_uid: str = Field(default_factory=lambda: NotSetEnum.NOT_SET)
    thumbnail_image_file_uid: str = Field(default_factory=lambda: NotSetEnum.NOT_SET)
    active_at: Optional[float] = Field(default_factory=lambda: NotSetEnum.NOT_SET)
    visible_in_admin: bool = Field(default_factory=lambda: NotSetEnum.NOT_SET)
    created_at: float = Field(default_factory=lambda: NotSetEnum.NOT_SET)

    active_onboarding_video_for_purpose_uid: Optional[str] = Field(
        default_factory=lambda: NotSetEnum.NOT_SET,
        description=(
            "The uid of the active onboarding video for the new purpose, if patching a purpose, "
            "otherwise for the current purpose."
        ),
    )

    @property
    def serd_purpose(self):
        return json.dumps(
            self.purpose.model_dump(), sort_keys=True, separators=(",", ":")
        )


class OnboardingVideoPatch(BaseModel):
    purpose: OnboardingVideoPurpose = Field(default_factory=lambda: NotSetEnum.NOT_SET)
    upload_uid: str = Field(default_factory=lambda: NotSetEnum.NOT_SET)
    thumbnail_uid: str = Field(default_factory=lambda: NotSetEnum.NOT_SET)
    active: Optional[bool] = Field(default_factory=lambda: NotSetEnum.NOT_SET)
    visible_in_admin: bool = Field(default_factory=lambda: NotSetEnum.NOT_SET)

    @property
    def serd_purpose(self):
        return json.dumps(
            self.purpose.model_dump(), sort_keys=True, separators=(",", ":")
        )


class PatchOnboardingVideoRequest(BaseModel):
    uid: str = Field(description="The uid of the onboarding video to update")
    precondition: OnboardingVideoPrecondition = Field(
        default_factory=lambda: OnboardingVideoPrecondition.model_validate({}),
        description=PRECONDITION_DOCS,
    )
    patch: OnboardingVideoPatch = Field(
        default_factory=lambda: OnboardingVideoPatch.model_validate({}),
        description=PATCH_DOCS,
    )


ERROR_404_TYPES = Literal[
    "onboarding_video_not_found",
    "onboarding_video_upload_not_found",
    "onboarding_video_thumbnail_not_found",
]

ERROR_409_TYPES = Literal["video_and_purpose_not_unique"]


@router.patch(
    "/",
    response_model=InternalOnboardingVideo,
    description=create_description("onboarding video")
    + "\n\nIf this update would cause there to be two onboarding videos active for the same purpose, "
    "this will cause the one _not_ specified in this request to become inactive.",
    responses={
        **create_responses(ERROR_404_TYPES),
        "409": {
            "description": (
                "You tried to change either the video via the upload_uid, or the purpose, "
                "but the new state of the onboarding video would have the same content file uid "
                "and purpose as another onboarding video, at which point you may as well just "
                "update the other onboarding video."
            ),
            "model": StandardErrorResponse[ERROR_409_TYPES],
        },
    },
)
async def patch_onboarding_video(
    args: PatchOnboardingVideoRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        patch_queries = do_patch(args.uid, args.precondition, args.patch)
        is_patch = not not patch_queries
        queries = [
            *check_preconditions(args.uid, args.patch, args.precondition),
            *check_subresources(args.patch),
            *check_conflicts(args.uid, args.patch),
            *patch_queries,
            do_read(args.uid),
        ]

        success, read_result_or_error_response = await handle_patch(
            itgs, queries, is_patch
        )
        if not success:
            return read_result_or_error_response

        read_result = cast(ResultItem, read_result_or_error_response)

        onboarding_video = await parse_read_result(itgs, read_result)
        return Response(
            content=onboarding_video.__pydantic_serializer__.to_json(onboarding_video),
            status_code=200,
            headers={
                "Content-Type": "application/json; charset=utf-8",
            },
        )


def _check_active_for_purpose(
    uid: str, patch: OnboardingVideoPatch, preconditions: OnboardingVideoPrecondition
) -> List[Query]:
    eq = preconditions.active_onboarding_video_for_purpose_uid
    if eq is NotSetEnum.NOT_SET:
        return []

    async def _check(item: ResultItem) -> None:
        if item.results:
            actual = item.results[0][0]
            raise PreconditionFailedException(
                "active_onboarding_video_for_purpose_uid", str(eq), str(actual)
            )

    if patch.purpose is NotSetEnum.NOT_SET:
        if eq is None:
            return [
                Query(
                    """
SELECT 
    uid 
FROM onboarding_videos 
WHERE 
    purpose=(SELECT ov.purpose FROM onboarding_videos AS ov WHERE ov.uid=?) 
    AND active_at IS NOT NULL
""",
                    [uid],
                    _check,
                )
            ]

        return [
            Query(
                """
SELECT 
    uid 
FROM onboarding_videos 
WHERE 
    purpose=(SELECT ov.purpose FROM onboarding_videos AS ov WHERE ov.uid=?) 
    AND active_at IS NOT NULL
    AND uid <> ?
""",
                [uid, eq],
                _check,
            )
        ]

    if eq is None:
        return [
            Query(
                """
SELECT 
    uid 
FROM onboarding_videos 
WHERE 
    purpose=?
    AND active_at IS NOT NULL
""",
                [patch.serd_purpose],
                _check,
            )
        ]

    return [
        Query(
            """
SELECT
    uid
FROM onboarding_videos
WHERE
    purpose=?
    AND active_at IS NOT NULL
    AND uid <> ?
""",
            [patch.serd_purpose, eq],
            _check,
        )
    ]


def check_preconditions(
    uid: str, patch: OnboardingVideoPatch, preconditions: OnboardingVideoPrecondition
) -> List[Query]:
    simple = partial(check_simple_precondition, "onboarding_videos", uid)
    joined = partial(check_joined_precondition, "onboarding_videos", uid)
    return [
        *simple(
            "purpose",
            (
                NotSetEnum.NOT_SET
                if preconditions.purpose is NotSetEnum.NOT_SET
                else preconditions.serd_purpose
            ),
        ),
        *simple("active_at", preconditions.active_at, threshold=1e-3),
        *simple("visible_in_admin", preconditions.visible_in_admin),
        *simple("created_at", preconditions.created_at, threshold=1e-3),
        *joined(
            "content_files",
            "video_content_file_id",
            "uid",
            preconditions.video_content_file_uid,
        ),
        *joined(
            "image_files",
            "thumbnail_image_file_id",
            "uid",
            preconditions.thumbnail_image_file_uid,
        ),
        *_check_active_for_purpose(uid, patch, preconditions),
    ]


def check_subresources(patch: OnboardingVideoPatch) -> List[Query]:
    async def _check(
        err_type: ERROR_404_TYPES, field: str, uid: str, r: ResultItem
    ) -> None:
        if not r.results:
            raise SubresourceMissingException(err_type, field, uid)

    result: List[Query] = []

    if patch.upload_uid is not NotSetEnum.NOT_SET:
        result.append(
            Query(
                "SELECT 1 FROM onboarding_video_uploads WHERE uid=?",
                [patch.upload_uid],
                partial(
                    _check,
                    "onboarding_video_upload_not_found",
                    "upload_uid",
                    patch.upload_uid,
                ),
            )
        )

    if patch.thumbnail_uid is not NotSetEnum.NOT_SET:
        result.append(
            Query(
                "SELECT 1 FROM onboarding_video_thumbnails WHERE uid=?",
                [patch.thumbnail_uid],
                partial(
                    _check,
                    "onboarding_video_thumbnail_not_found",
                    "thumbnail_uid",
                    patch.thumbnail_uid,
                ),
            )
        )

    return result


def _check_content_file_id_purpose_uniqueness(
    uid: str, patch: OnboardingVideoPatch
) -> List[Query]:
    if patch.purpose is NotSetEnum.NOT_SET and patch.upload_uid is NotSetEnum.NOT_SET:
        return []

    async def _check(message: str, item: ResultItem) -> None:
        if item.results:
            raise ConflictException(
                "video_and_purpose_not_unique",
                "purpose",
                item.results[0][0],
                Response(
                    status_code=409,
                    content=StandardErrorResponse[ERROR_409_TYPES](
                        type="video_and_purpose_not_unique",
                        message=message,
                    ).model_dump_json(),
                    headers={"Content-Type": "application/json; charset=utf-8"},
                ),
            )

    if patch.purpose is NotSetEnum.NOT_SET:
        return [
            Query(
                """
SELECT
    uid
FROM onboarding_videos
WHERE
    purpose = (SELECT ov.purpose FROM onboarding_videos AS ov WHERE ov.uid=?)
    AND video_content_file_id = (
        SELECT ovu.content_file_id FROM onboarding_video_uploads AS ovu WHERE ovu.uid=?
    )
    AND uid <> ?
""",
                [uid, patch.upload_uid, uid],
                partial(
                    _check,
                    "there is already another video with the same purpose and the new content file",
                ),
            )
        ]

    if patch.upload_uid is NotSetEnum.NOT_SET:
        return [
            Query(
                """
SELECT
    uid
FROM onboarding_videos
WHERE
    purpose = ?
    AND video_content_file_id = (
        SELECT ov.video_content_file_id FROM onboarding_videos AS ov WHERE ov.uid=?
    )
    AND uid <> ?
""",
                [patch.serd_purpose, uid, uid],
                partial(
                    _check,
                    "there is already another video with the same content file and the new purpose",
                ),
            )
        ]

    return [
        Query(
            """
SELECT
    uid
FROM onboarding_videos
WHERE
    purpose = ?
    AND video_content_file_id = (
        SELECT ovu.content_file_id FROM onboarding_video_uploads AS ovu WHERE ovu.uid=?
    )
    AND uid <> ?
""",
            [patch.serd_purpose, patch.upload_uid, uid],
            partial(
                _check,
                "there is already another video with the new content file and the new purpose",
            ),
        )
    ]


def check_conflicts(uid: str, patch: OnboardingVideoPatch) -> List[Query]:
    return _check_content_file_id_purpose_uniqueness(uid, patch)


def _checked_onboarding_videos(
    uid: str,
    patch: OnboardingVideoPatch,
    precondition: OnboardingVideoPrecondition,
    qargs: list,
) -> str:
    """Returns an expression like

    checked_onboarding_videos(id, uid) AS (...)

    which will be populated with 0 or 1 rows, depending on whether the
    course meets the preconditions AND all of the subresources required
    for the patch exist.

    Args:
        uid (str): the uid of the onboarding video; if a row is populated in the
            result, it will have this uid
        patch (CoursePatchSimple): the patch to apply
        precondition (CoursePreconditionSimple): the precondition to check
        qargs (list): the list of arguments to the query
    """
    result = io.StringIO()
    result.write(
        "checked_onboarding_videos(id, uid) AS ("
        "SELECT onboarding_videos.id, onboarding_videos.uid FROM onboarding_videos "
        "WHERE onboarding_videos.uid=?"
    )
    qargs.append(uid)

    if precondition.purpose is not NotSetEnum.NOT_SET:
        result.write(" AND onboarding_videos.purpose=?")
        qargs.append(precondition.serd_purpose)

    if precondition.video_content_file_uid is not NotSetEnum.NOT_SET:
        result.write(
            " AND onboarding_videos.video_content_file_id="
            "(SELECT content_files.id FROM content_files WHERE content_files.uid=?)"
        )
        qargs.append(precondition.video_content_file_uid)

    if precondition.thumbnail_image_file_uid is not NotSetEnum.NOT_SET:
        result.write(
            " AND onboarding_videos.thumbnail_image_file_id="
            "(SELECT image_files.id FROM image_files WHERE image_files.uid=?)"
        )
        qargs.append(precondition.thumbnail_image_file_uid)

    if precondition.active_at is not NotSetEnum.NOT_SET:
        if precondition.active_at is not None:
            result.write(
                " AND onboarding_videos.active_at>? AND onboarding_videos.active_at<?"
            )
            qargs.append(precondition.active_at - 1e-3)
            qargs.append(precondition.active_at + 1e-3)
        else:
            result.write(" AND onboarding_videos.active_at IS NULL")

    if precondition.visible_in_admin is not NotSetEnum.NOT_SET:
        result.write(" AND onboarding_videos.visible_in_admin=?")
        qargs.append(int(precondition.visible_in_admin))

    if precondition.created_at is not NotSetEnum.NOT_SET:
        result.write(
            " AND onboarding_videos.created_at>? AND onboarding_videos.created_at<?"
        )
        qargs.append(precondition.created_at - 1e-3)
        qargs.append(precondition.created_at + 1e-3)

    if precondition.active_onboarding_video_for_purpose_uid is not NotSetEnum.NOT_SET:
        result.write(
            " AND (SELECT ov.uid FROM onboarding_videos AS ov WHERE ov.purpose="
        )
        if patch.purpose is NotSetEnum.NOT_SET:
            result.write(
                "(SELECT ov2.purpose FROM onboarding_videos AS ov2 WHERE ov2.uid=?)"
            )
            qargs.append(uid)
        else:
            result.write("?")
            qargs.append(patch.serd_purpose)
        result.write(" AND ov.active_at IS NOT NULL)")
        if precondition.active_onboarding_video_for_purpose_uid is None:
            result.write(" IS NULL")
        else:
            result.write(" = ?")
            qargs.append(precondition.active_onboarding_video_for_purpose_uid)

    if patch.upload_uid is not NotSetEnum.NOT_SET:
        result.write(
            " AND EXISTS (SELECT 1 FROM onboarding_video_uploads WHERE onboarding_video_uploads.uid=?)"
        )
        qargs.append(patch.upload_uid)

    if patch.thumbnail_uid is not NotSetEnum.NOT_SET:
        result.write(
            " AND EXISTS (SELECT 1 FROM onboarding_video_thumbnails WHERE onboarding_video_thumbnails.uid=?)"
        )
        qargs.append(patch.thumbnail_uid)

    result.write(")")
    return result.getvalue()


def do_patch(
    uid: str, preconditions: OnboardingVideoPrecondition, patch: OnboardingVideoPatch
) -> List[Query]:
    updates: List[str] = []
    update_qargs: List[Any] = []

    if patch.purpose is not NotSetEnum.NOT_SET:
        updates.append("purpose = ?")
        update_qargs.append(patch.serd_purpose)

    if patch.upload_uid is not NotSetEnum.NOT_SET:
        updates.append(
            "video_content_file_id = (SELECT onboarding_video_uploads.content_file_id WHERE onboarding_video_uploads.uid = ?)"
        )
        update_qargs.append(patch.upload_uid)

    if patch.thumbnail_uid is not NotSetEnum.NOT_SET:
        updates.append(
            "thumbnail_image_file_id = (SELECT onboarding_video_thumbnails.image_file_id WHERE onboarding_video_thumbnails.uid = ?)"
        )
        update_qargs.append(patch.thumbnail_uid)

    if patch.active is not NotSetEnum.NOT_SET:
        if patch.active:
            updates.append("active_at = ?")
            update_qargs.append(time.time())
        else:
            updates.append("active_at = NULL")

    if patch.visible_in_admin is not NotSetEnum.NOT_SET:
        updates.append("visible_in_admin = ?")
        update_qargs.append(int(patch.visible_in_admin))

    if not updates:
        return []

    is_simple_update = patch.active is False or (
        patch.active is NotSetEnum.NOT_SET
        and preconditions.active_at is None
        and patch.purpose is NotSetEnum.NOT_SET
    )
    update_preconditions = preconditions
    if not is_simple_update:
        update_preconditions = update_preconditions.model_copy()
        update_preconditions.active_onboarding_video_for_purpose_uid = None

    update_sql = ", ".join(updates)

    query = io.StringIO()
    qargs = []

    query.write("WITH ")
    query.write(_checked_onboarding_videos(uid, patch, update_preconditions, qargs))
    query.write(" UPDATE onboarding_videos SET ")
    query.write(update_sql)
    qargs.extend(update_qargs)
    query.write(
        " FROM checked_onboarding_videos WHERE onboarding_videos.id=checked_onboarding_videos.id"
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

    update_this_row = Query(query.getvalue(), qargs, _check)

    if is_simple_update:
        return [update_this_row]

    async def _check_unset_active(r: ResultItem) -> None:
        if r.rows_affected is not None and r.rows_affected > 1:
            await handle_warning(
                f"{__name__}:unset_active_multiple",
                f"expected to update 0 or 1 rows to replace active, but updated {r.rows_affected}",
                is_urgent=True,
            )

    query = io.StringIO()
    qargs = []

    query.write("WITH ")
    query.write(_checked_onboarding_videos(uid, patch, preconditions, qargs))
    query.write(
        " UPDATE onboarding_videos SET active_at=NULL "
        "WHERE EXISTS (SELECT 1 FROM checked_onboarding_videos)"
        " AND onboarding_videos.active_at IS NOT NULL"
        " AND onboarding_videos.uid <> ?"
    )
    qargs.append(uid)

    if patch.active is not True:
        query.write(
            " AND EXISTS (SELECT 1 FROM onboarding_videos AS ov WHERE ov.uid=? AND ov.active_at IS NOT NULL)"
        )
        qargs.append(uid)

    if patch.purpose is not NotSetEnum.NOT_SET:
        query.write(" AND onboarding_videos.purpose=?")
        qargs.append(patch.serd_purpose)
    else:
        query.write(
            " AND onboarding_videos.purpose=(SELECT ov.purpose FROM onboarding_videos AS ov WHERE ov.uid=?)"
        )
        qargs.append(uid)

    unset_active = Query(query.getvalue(), qargs, _check_unset_active)
    return [unset_active, update_this_row]


def do_read(uid: str) -> Query:
    async def _check(r: ResultItem) -> None:
        if not r.results:
            raise SubresourceMissingException("onboarding_video_not_found", "uid", uid)

    return Query(
        f"{STANDARD_INTERNAL_ONBOARDING_VIDEO_ROW_SELECT_JOIN} WHERE onboarding_videos.uid=?",
        [uid],
        _check,
    )


async def parse_read_result(itgs: Itgs, r: ResultItem) -> InternalOnboardingVideo:
    assert r.results

    row = r.results[0]
    return await parse_internal_onboarding_video_row(
        itgs, row=InternalOnboardingVideoRow(*row)
    )
