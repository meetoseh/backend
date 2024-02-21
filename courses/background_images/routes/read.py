from pypika import Table, Query, Parameter
from pypika.queries import QueryBuilder
from pypika.terms import Term
from typing import Annotated, Any, Dict, List, Literal, Optional, Tuple, Union, cast
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE
from resources.filter import sort_criterion, flattened_filters
from resources.filter_item import FilterItemModel
from resources.filter_item_like import FilterItemLike
from resources.sort import cleanup_sort, get_next_page_sort, reverse_sort
from resources.sort_item import SortItem, SortItemModel
from resources.filter_text_item import FilterTextItemModel
from itgs import Itgs
import image_files.auth as image_files_auth
from image_files.models import ImageFileRef


class CourseBackgroundImage(BaseModel):
    uid: str = Field(description="The primary stable external identifier for this row")
    original_image_file: ImageFileRef = Field(description="The underlying image file")
    darkened_image_file: ImageFileRef = Field(
        description="The darkened variant of the image file"
    )
    image_file_created_at: float = Field(
        description="When the image file was originally uploaded, in seconds since the epoch"
    )
    last_uploaded_at: float = Field(
        description="the last time this file was uploaded, in seconds since the epoch"
    )


COURSE_BACKGROUND_IMAGE_SORT_OPTIONS = [
    SortItem[Literal["uid"], str],
    SortItem[Literal["image_file_created_at"], float],
    SortItem[Literal["last_uploaded_at"], float],
]
CourseBackgroundImageSortOption = Union[
    SortItemModel[Literal["uid"], str],
    SortItemModel[Literal["image_file_created_at"], float],
    SortItemModel[Literal["last_uploaded_at"], float],
]


class CourseBackgroundImageFilter(BaseModel):
    uid: Optional[FilterTextItemModel] = Field(
        None, description="the uid of the course logo row"
    )
    original_image_file_uid: Optional[FilterTextItemModel] = Field(
        None, description="the uid of the original image file"
    )
    darkened_image_file_uid: Optional[FilterTextItemModel] = Field(
        None, description="the uid of the darkened image file"
    )
    original_file_sha512: Optional[FilterTextItemModel] = Field(
        None, description="the sha512 of the original image that was processed"
    )
    last_uploaded_at: Optional[FilterItemModel[float]] = Field(
        None, description="the last time the file was uploaded"
    )


class ReadCourseBackgroundImageRequest(BaseModel):
    filters: CourseBackgroundImageFilter = Field(
        default_factory=lambda: CourseBackgroundImageFilter.model_validate({}),
        description="the filters to apply",
    )
    sort: Optional[List[CourseBackgroundImageSortOption]] = Field(
        None, description="the sort order to apply"
    )
    limit: int = Field(
        25, description="the maximum number of rows to return", ge=1, le=250
    )


class ReadCourseBackgroundImageResponse(BaseModel):
    items: List[CourseBackgroundImage] = Field(
        description="the items matching the filters in the given sort"
    )
    next_page_sort: Optional[List[CourseBackgroundImageSortOption]] = Field(
        None, description="if there is a next or earlier page, the sort order to get it"
    )


router = APIRouter()


@router.post(
    "/search",
    response_model=ReadCourseBackgroundImageResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_course_background_images(
    args: ReadCourseBackgroundImageRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Lists out course background images

    This requires standard authorization for a user with admin access
    """
    sort = [srt.to_result() for srt in (args.sort or [])]
    sort = cleanup_sort(COURSE_BACKGROUND_IMAGE_SORT_OPTIONS, sort, ["uid"])
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response
        filters_to_apply = flattened_filters(
            dict(
                (k, cast(FilterItemLike, v.to_result()))
                for k, v in args.filters.__dict__.items()
                if v is not None
            )
        )
        items = await raw_read_course_background_images(
            itgs, filters_to_apply, sort, args.limit + 1
        )
        next_page_sort: Optional[List[SortItem]] = None
        last_item: Optional[Dict[str, Any]] = None
        if len(items) > args.limit:
            items = items[: args.limit]
            last_item = item_pseudocolumns(items[-1])
        first_item: Optional[Dict[str, Any]] = None
        if items and any(s.after is not None for s in sort):
            rev_sort = reverse_sort(sort, "make_exclusive")
            rev_items = await raw_read_course_background_images(
                itgs, filters_to_apply, rev_sort, 1
            )
            if rev_items:
                first_item = item_pseudocolumns(items[0])

        if first_item is not None or last_item is not None:
            next_page_sort = get_next_page_sort(first_item, last_item, sort)

        return Response(
            content=ReadCourseBackgroundImageResponse.__pydantic_serializer__.to_json(
                ReadCourseBackgroundImageResponse(
                    items=items,
                    next_page_sort=(
                        [s.to_model() for s in next_page_sort]
                        if next_page_sort is not None
                        else None
                    ),
                )
            ),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )


async def raw_read_course_background_images(
    itgs: Itgs,
    filters_to_apply: List[Tuple[str, FilterItemLike]],
    sort: List[SortItem],
    limit: int,
) -> List[CourseBackgroundImage]:
    """performs exactly the specified sort without pagination logic"""
    course_background_images = Table("course_background_images")
    image_files = Table("image_files")
    original_image_files = image_files.as_("original_image_files")
    darkened_image_files = image_files.as_("darkened_image_files")

    query: QueryBuilder = (
        Query.from_(course_background_images)
        .select(
            course_background_images.uid,
            original_image_files.uid,
            darkened_image_files.uid,
            original_image_files.created_at,
            course_background_images.last_uploaded_at,
        )
        .join(original_image_files)
        .on(original_image_files.id == course_background_images.original_image_file_id)
        .join(darkened_image_files)
        .on(darkened_image_files.id == course_background_images.darkened_image_file_id)
    )
    qargs = []

    def pseudocolumn(key: str) -> Term:
        if key == "uid":
            return course_background_images.field("uid")
        elif key == "image_file_created_at":
            return original_image_files.field("created_at")
        elif key == "original_image_file_uid":
            return original_image_files.field("uid")
        elif key == "darkened_image_file_uid":
            return darkened_image_files.field("uid")
        elif key == "original_file_sha512":
            return original_image_files.field("original_sha512")
        elif key == "last_uploaded_at":
            return course_background_images.field("last_uploaded_at")

        raise ValueError(f"Unknown pseudocolumn {key}")

    for key, filter in filters_to_apply:
        query = query.where(filter.applied_to(pseudocolumn(key), qargs))

    query = query.where(sort_criterion(sort, pseudocolumn, qargs))

    for srt in sort:
        query = query.orderby(pseudocolumn(srt.key), order=srt.order)

    query = query.limit(Parameter("?"))
    qargs.append(limit)

    conn = await itgs.conn()
    cursor = conn.cursor("none")
    response = await cursor.execute(query.get_sql(), qargs)
    items: List[CourseBackgroundImage] = []
    for row in response.results or []:
        items.append(
            CourseBackgroundImage(
                uid=row[0],
                original_image_file=ImageFileRef(
                    uid=row[1], jwt=await image_files_auth.create_jwt(itgs, row[1])
                ),
                darkened_image_file=ImageFileRef(
                    uid=row[2], jwt=await image_files_auth.create_jwt(itgs, row[2])
                ),
                image_file_created_at=row[3],
                last_uploaded_at=row[4],
            )
        )
    return items


def item_pseudocolumns(item: CourseBackgroundImage) -> dict:
    """returns the dictified item such that the keys in the return dict match
    the keys of the sort options"""
    return {
        "uid": item.uid,
        "image_file_created_at": item.image_file_created_at,
        "last_uploaded_at": item.last_uploaded_at,
    }
