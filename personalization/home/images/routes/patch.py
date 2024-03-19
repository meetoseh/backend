from functools import partial
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
    cast,
)
from auth import auth_admin
from rqdb.result import ResultItem
from error_middleware import handle_warning
from itgs import Itgs
from personalization.home.images.lib.internal_home_screen_image import (
    STANDARD_INTERNAL_HOME_SCREEN_IMAGE_ROW_SELECT_JOIN,
    InternalHomeScreenImage,
    InternalHomeScreenImageRow,
    parse_internal_home_screen_image_row,
)
from resources.patch.docs import (
    PATCH_DOCS,
    PRECONDITION_DOCS,
    create_description,
    create_responses,
)
from resources.patch.exceptions import (
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
from users.lib.home_screen_images import purge_home_screen_images_cache

router = APIRouter()


class HomeScreenImagePreconditionModel(BaseModel):
    image_file_uid: str = Field(default_factory=lambda: NotSetEnum.NOT_SET)
    darkened_image_file_uid: str = Field(default_factory=lambda: NotSetEnum.NOT_SET)
    start_time: int = Field(default_factory=lambda: NotSetEnum.NOT_SET)
    end_time: int = Field(default_factory=lambda: NotSetEnum.NOT_SET)
    flags: int = Field(default_factory=lambda: NotSetEnum.NOT_SET)
    dates: Optional[List[str]] = Field(
        default_factory=lambda: NotSetEnum.NOT_SET,
        description="This precondition is sensitive to the order",
    )
    created_at: float = Field(default_factory=lambda: NotSetEnum.NOT_SET)
    live_at: float = Field(default_factory=lambda: NotSetEnum.NOT_SET)


class HomeScreenImagePatchModel(BaseModel):
    start_time: int = Field(default_factory=lambda: NotSetEnum.NOT_SET)
    end_time: int = Field(default_factory=lambda: NotSetEnum.NOT_SET)
    flags: int = Field(default_factory=lambda: NotSetEnum.NOT_SET)
    dates: Optional[List[str]] = Field(default_factory=lambda: NotSetEnum.NOT_SET)
    live_at: float = Field(default_factory=lambda: NotSetEnum.NOT_SET)


class PatchHomeScreenImageRequest(BaseModel):
    uid: str = Field(description="The uid of the home screen image to update")
    precondition: HomeScreenImagePreconditionModel = Field(
        default_factory=lambda: HomeScreenImagePreconditionModel.model_validate({}),
        description=PRECONDITION_DOCS,
    )
    patch: HomeScreenImagePatchModel = Field(
        default_factory=lambda: HomeScreenImagePatchModel.model_validate({}),
        description=PATCH_DOCS,
    )


ERROR_404_TYPES = Literal["home_screen_image_not_found"]


@router.patch(
    "/",
    response_model=InternalHomeScreenImage,
    description=create_description("home screen image"),
    responses=create_responses(ERROR_404_TYPES),
)
async def patch_home_screen_image(
    args: PatchHomeScreenImageRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        patch_queries = do_patch(args.uid, args.precondition, args.patch)
        is_patch = not not patch_queries
        queries = [
            *check_preconditions(args.uid, args.precondition),
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

        if is_patch:
            await purge_home_screen_images_cache(itgs)

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


def check_preconditions(
    uid: str, preconditions: HomeScreenImagePreconditionModel
) -> List[Query]:
    simple = partial(check_simple_precondition, "home_screen_images", uid)
    joined = partial(check_joined_precondition, "home_screen_images", uid)
    return [
        *simple("start_time", preconditions.start_time),
        *simple("end_time", preconditions.end_time),
        *simple("flags", preconditions.flags),
        *simple(
            "dates",
            (
                (
                    None
                    if preconditions.dates is None
                    else json.dumps(preconditions.dates, separators=(",", ":"))
                )
                if preconditions.dates is not NotSetEnum.NOT_SET
                else NotSetEnum.NOT_SET
            ),
        ),
        *simple("created_at", preconditions.created_at),
        *simple("live_at", preconditions.live_at),
        *joined(
            "image_files",
            "image_file_id",
            "uid",
            preconditions.image_file_uid,
        ),
        *joined(
            "image_files",
            "darkened_image_file_id",
            "uid",
            preconditions.darkened_image_file_uid,
        ),
    ]


def check_subresources(patch: HomeScreenImagePatchModel) -> List[Query]:
    return []


def _checked_home_screen_images(
    uid: str,
    patch: HomeScreenImagePatchModel,
    precondition: HomeScreenImagePreconditionModel,
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

    if precondition.image_file_uid is not NotSetEnum.NOT_SET:
        result.write(
            " JOIN image_files ON image_files.id = home_screen_images.image_file_id"
        )

    if precondition.darkened_image_file_uid is not NotSetEnum.NOT_SET:
        result.write(
            " JOIN image_files AS darkened_image_files "
            "ON darkened_image_files.id = home_screen_images.darkened_image_file_id"
        )

    result.write(" WHERE home_screen_images.uid = ?")
    qargs.append(uid)

    if precondition.image_file_uid is not NotSetEnum.NOT_SET:
        if precondition.image_file_uid is None:
            result.write(" AND image_files.id IS NULL")
        else:
            result.write(" AND image_files.uid = ?")
            qargs.append(precondition.image_file_uid)

    if precondition.darkened_image_file_uid is not NotSetEnum.NOT_SET:
        if precondition.darkened_image_file_uid is None:
            result.write(" AND darkened_image_files.id IS NULL")
        else:
            result.write(" AND darkened_image_files.uid = ?")
            qargs.append(precondition.darkened_image_file_uid)

    if precondition.start_time is not NotSetEnum.NOT_SET:
        result.write(" AND home_screen_images.start_time = ?")
        qargs.append(precondition.start_time)

    if precondition.end_time is not NotSetEnum.NOT_SET:
        result.write(" AND home_screen_images.end_time = ?")
        qargs.append(precondition.end_time)

    if precondition.flags is not NotSetEnum.NOT_SET:
        result.write(" AND home_screen_images.flags = ?")
        qargs.append(precondition.flags)

    if precondition.dates is not NotSetEnum.NOT_SET:
        if precondition.dates is None:
            result.write(" AND home_screen_images.dates IS NULL")
        else:
            result.write(" AND home_screen_images.dates = ?")
            qargs.append(json.dumps(precondition.dates, separators=(",", ":")))

    if precondition.live_at is not NotSetEnum.NOT_SET:
        result.write(" AND home_screen_images.live_at = ?")
        qargs.append(precondition.live_at)

    if precondition.created_at is not NotSetEnum.NOT_SET:
        result.write(" AND home_screen_images.created_at = ?")
        qargs.append(precondition.created_at)

    result.write(")")
    return result.getvalue()


def do_patch(
    uid: str,
    preconditions: HomeScreenImagePreconditionModel,
    patch: HomeScreenImagePatchModel,
) -> List[Query]:
    updates: List[str] = []
    update_qargs: List[Any] = []

    if patch.start_time is not NotSetEnum.NOT_SET:
        updates.append("start_time = ?")
        update_qargs.append(patch.start_time)

    if patch.end_time is not NotSetEnum.NOT_SET:
        updates.append("end_time = ?")
        update_qargs.append(patch.end_time)

    if patch.flags is not NotSetEnum.NOT_SET:
        updates.append("flags = ?")
        update_qargs.append(patch.flags)

    if patch.dates is not NotSetEnum.NOT_SET:
        if patch.dates is None:
            updates.append("dates = NULL")
        else:
            updates.append("dates = ?")
            update_qargs.append(
                json.dumps(patch.dates, separators=(",", ":"), sort_keys=True)
            )

    if patch.live_at is not NotSetEnum.NOT_SET:
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
            raise UpdateFailedException()

    return [Query(query.getvalue(), qargs, _check)]


def do_read(uid: str) -> Query:
    async def _check(r: ResultItem) -> None:
        if not r.results:
            raise SubresourceMissingException[ERROR_404_TYPES](
                "home_screen_image_not_found", "home_screen_image", uid
            )

    return Query(
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
