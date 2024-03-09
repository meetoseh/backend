from pypika import Table, Query, Parameter, Not
from pypika.queries import QueryBuilder
from pypika.terms import Term, Function, ExistsCriterion
from typing import Any, Dict, List, Literal, Optional, Tuple, Union, cast
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from auth import auth_admin
from db.utils import TableValuedFunction
from models import STANDARD_ERRORS_BY_CODE
from personalization.home.images.lib.internal_home_screen_image import (
    InternalHomeScreenImage,
    InternalHomeScreenImageRow,
    parse_internal_home_screen_image_row,
)
from resources.filter import sort_criterion, flattened_filters
from resources.filter_bit_field_item import FilterBitFieldItemModel
from resources.filter_item import FilterItemModel
from resources.filter_item_like import FilterItemLike
from resources.sort import cleanup_sort, get_next_page_sort, reverse_sort
from resources.sort_item import SortItem, SortItemModel
from resources.filter_text_item import FilterTextItemModel
from itgs import Itgs


HOME_SCREEN_IMAGE_SORT_OPTIONS = [
    SortItem[Literal["uid"], str],
    SortItem[Literal["created_at"], float],
]
HomeScreenImageSortOption = Union[
    SortItemModel[Literal["uid"], str],
    SortItemModel[Literal["created_at"], float],
]


class HomeScreenImageFilter(BaseModel):
    uid: Optional[FilterTextItemModel] = Field(
        None, description="primary stable external row identifier"
    )
    image_file_uid: Optional[FilterTextItemModel] = Field(
        None, description="primary stable external row identifier of the original image"
    )
    image_file_original_sha512: Optional[FilterTextItemModel] = Field(
        None, description="the SHA-512 hash of the source of the original image file"
    )
    darkened_image_file_uid: Optional[FilterTextItemModel] = Field(
        None, description="primary stable external row identifier of the darkened image"
    )
    start_time: Optional[FilterItemModel[float]] = Field(
        None,
        description="minimum number of seconds from local midnight when the image can be shown",
    )
    end_time: Optional[FilterItemModel[float]] = Field(
        None,
        description="maximum number of seconds from local midnight when the image can be shown",
    )
    flags: Optional[FilterBitFieldItemModel] = Field(
        None, description="twos-complement 64-bit integer boolean access flags"
    )
    dates_length: Optional[FilterItemModel[int]] = Field(
        None,
        description="the number of dates in the dates list, null for unset",
    )
    any_date: Optional[FilterTextItemModel] = Field(
        None, description="If set, rows only match if dates is set and contains a match"
    )
    all_dates: Optional[FilterTextItemModel] = Field(
        None,
        description="If set, rows only match if dates is set and each date matches",
    )
    created_at: Optional[FilterItemModel[float]] = Field(
        None,
        description="when the row was created in seconds since the epoch",
    )
    live_at: Optional[FilterItemModel[float]] = Field(
        None,
        description=(
            "this image cannot be shown earlier than this time in seconds since the unix epoch"
        ),
    )


class ReadHomeScreenImageRequest(BaseModel):
    filters: HomeScreenImageFilter = Field(
        default_factory=lambda: HomeScreenImageFilter.model_validate({}),
        description="the filters to apply",
    )
    sort: Optional[List[HomeScreenImageSortOption]] = Field(
        None, description="the order to sort by"
    )
    limit: int = Field(
        25, description="the maximum number of images to return", ge=1, le=250
    )


class ReadHomeScreenImageResponse(BaseModel):
    items: List[InternalHomeScreenImage] = Field(
        description="the items matching the filters in the given sort"
    )
    next_page_sort: Optional[List[HomeScreenImageSortOption]] = Field(
        description=(
            "if there is a next page or an earlier page, provides the necessary "
            "sort criteria to get it"
        )
    )


router = APIRouter()


@router.post(
    "/search",
    response_model=ReadHomeScreenImageResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_home_screen_images(
    args: ReadHomeScreenImageRequest, authorization: Optional[str] = Header(None)
):
    """Lists out home screen images

    This requires standard authentication with an admin account.
    """
    sort = [srt.to_result() for srt in (args.sort or [])]
    sort = cleanup_sort(HOME_SCREEN_IMAGE_SORT_OPTIONS, sort, ["uid"])
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
        items = await raw_read_home_screen_images(
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
            rev_items = await raw_read_home_screen_images(
                itgs, filters_to_apply, rev_sort, 1
            )
            if rev_items:
                first_item = item_pseudocolumns(items[0])

        if first_item is not None or last_item is not None:
            next_page_sort = get_next_page_sort(first_item, last_item, sort)

        return Response(
            content=ReadHomeScreenImageResponse(
                items=items,
                next_page_sort=(
                    [s.to_model() for s in next_page_sort]
                    if next_page_sort is not None
                    else None
                ),
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )


async def raw_read_home_screen_images(
    itgs: Itgs,
    filters_to_apply: List[Tuple[str, FilterItemLike]],
    sort: List[SortItem],
    limit: int,
):
    """performs exactly the specified sort without pagination logic"""
    home_screen_images = Table("home_screen_images")
    _image_files = Table("image_files")
    original_image_files = _image_files.as_("original_image_files")
    darkened_image_files = _image_files.as_("darkened_image_files")
    dates = TableValuedFunction(
        Function("json_each", home_screen_images.field("dates")), "dates"
    )

    query: QueryBuilder = (
        Query.from_(home_screen_images)
        .select(
            home_screen_images.uid,
            original_image_files.uid,
            darkened_image_files.uid,
            home_screen_images.start_time,
            home_screen_images.end_time,
            home_screen_images.flags,
            home_screen_images.dates,
            home_screen_images.created_at,
            home_screen_images.live_at,
        )
        .join(original_image_files)
        .on(original_image_files.id == home_screen_images.image_file_id)
        .join(darkened_image_files)
        .on(darkened_image_files.id == home_screen_images.darkened_image_file_id)
    )
    qargs = []

    def pseudocolumn(key: str) -> Term:
        if key in (
            "uid",
            "start_time",
            "end_time",
            "flags",
            "dates",
            "created_at",
            "live_at",
        ):
            return home_screen_images.field(key)
        elif key == "image_file_uid":
            return original_image_files.field("uid")
        elif key == "image_file_original_sha512":
            return original_image_files.field("original_sha512")
        elif key == "darkened_image_file_uid":
            return darkened_image_files.field("uid")
        elif key == "dates_length":
            return Function("json_array_length", home_screen_images.field("dates"))
        raise ValueError(f"unknown key {key}")

    for key, filter in filters_to_apply:
        if key == "any_date":
            query = query.where(
                ExistsCriterion(
                    Query.from_(dates)
                    .select(1)
                    .where(filter.applied_to(dates.field("value"), qargs))
                )
            )
        elif key == "all_dates":
            query = query.where(
                Not(
                    ExistsCriterion(
                        Query.from_(dates)
                        .select(1)
                        .where(Not(filter.applied_to(dates.field("value"), qargs)))
                    )
                )
            )
        else:
            query = query.where(filter.applied_to(pseudocolumn(key), qargs))

    query = query.where(sort_criterion(sort, pseudocolumn, qargs))

    for srt in sort:
        query = query.orderby(pseudocolumn(srt.key), order=srt.order)

    query = query.limit(Parameter("?"))
    qargs.append(limit)

    conn = await itgs.conn()
    cursor = conn.cursor("none")
    response = await cursor.execute(query.get_sql(), qargs)
    items: List[InternalHomeScreenImage] = []
    for row in response.results or []:
        items.append(
            await parse_internal_home_screen_image_row(
                itgs, row=InternalHomeScreenImageRow(*row)
            )
        )
    return items


def item_pseudocolumns(item: InternalHomeScreenImage) -> dict:
    """returns the dictified item such that the keys in the return dict match
    the keys of the sort options"""
    return {
        "uid": item.uid,
        "created_at": item.created_at,
    }
