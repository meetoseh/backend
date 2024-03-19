from pypika import Table, Query, Parameter
from pypika.queries import QueryBuilder
from pypika.terms import Term, Function
from typing import Any, Dict, List, Literal, Optional, Tuple, Union, cast
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE
from onboarding.videos.lib.internal_onboarding_video import (
    InternalOnboardingVideo,
    InternalOnboardingVideoRow,
    parse_internal_onboarding_video_row,
)
from resources.filter import sort_criterion, flattened_filters
from resources.filter_item import FilterItemModel
from resources.filter_item_like import FilterItemLike
from resources.sort import cleanup_sort, get_next_page_sort, reverse_sort
from resources.sort_item import SortItem, SortItemModel
from resources.filter_text_item import FilterTextItemModel
from itgs import Itgs


ONBOARDING_VIDEO_SORT_OPTIONS = [
    SortItem[Literal["purpose_type"], str],
    SortItem[Literal["uid"], str],
    SortItem[Literal["created_at"], float],
]
OnboardingVideoSortOption = Union[
    SortItemModel[Literal["purpose_type"], str],
    SortItemModel[Literal["uid"], str],
    SortItemModel[Literal["created_at"], float],
]


class OnboardingVideoFilter(BaseModel):
    uid: Optional[FilterTextItemModel] = Field(
        None, description="primary stable external row identifier"
    )
    purpose_type: Optional[FilterTextItemModel] = Field(
        None, description="The type of the purpose of the video"
    )
    purpose: Optional[FilterTextItemModel] = Field(
        None,
        description="The exact purpose of this video, as a json object, sorted keys, no unnecessary whitespace",
    )
    video_content_file_uid: Optional[FilterTextItemModel] = Field(
        None, description="The uid of the video content file"
    )
    video_content_file_original_sha512: Optional[FilterTextItemModel] = Field(
        None, description="The sha512 of the original file for the video content"
    )
    thumbnail_image_file_uid: Optional[FilterTextItemModel] = Field(
        None, description="The uid of the thumbnail image file"
    )
    thumbnail_image_file_original_sha512: Optional[FilterTextItemModel] = Field(
        None, description="The sha512 of the original file for the thumbnail image"
    )
    active_at: Optional[FilterItemModel[float]] = Field(
        None, description="when the active flag was most recently set for this row"
    )
    visible_in_admin: Optional[FilterItemModel[bool]] = Field(
        None, description="A value which is only used for filtering in admin"
    )
    created_at: Optional[FilterItemModel[float]] = Field(
        None,
        description="when the row was created in seconds since the epoch",
    )


class ReadOnboardingVideoRequest(BaseModel):
    filters: OnboardingVideoFilter = Field(
        default_factory=lambda: OnboardingVideoFilter.model_validate({}),
        description="the filters to apply",
    )
    sort: Optional[List[OnboardingVideoSortOption]] = Field(
        None, description="the order to sort by"
    )
    limit: int = Field(
        25, description="the maximum number of images to return", ge=1, le=250
    )


class ReadOnboardingVideoResponse(BaseModel):
    items: List[InternalOnboardingVideo] = Field(
        description="the items matching the filters in the given sort"
    )
    next_page_sort: Optional[List[OnboardingVideoSortOption]] = Field(
        description=(
            "if there is a next page or an earlier page, provides the necessary "
            "sort criteria to get it"
        )
    )


router = APIRouter()


@router.post(
    "/search",
    response_model=ReadOnboardingVideoResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_onboarding_videos(
    args: ReadOnboardingVideoRequest, authorization: Optional[str] = Header(None)
):
    """Lists out onboarding videos

    This requires standard authentication with an admin account.
    """
    sort = [srt.to_result() for srt in (args.sort or [])]
    sort = cleanup_sort(ONBOARDING_VIDEO_SORT_OPTIONS, sort, ["uid"])
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
        items = await raw_read_onboarding_videos(
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
            rev_items = await raw_read_onboarding_videos(
                itgs, filters_to_apply, rev_sort, 1
            )
            if rev_items:
                first_item = item_pseudocolumns(items[0])

        if first_item is not None or last_item is not None:
            next_page_sort = get_next_page_sort(first_item, last_item, sort)

        return Response(
            content=ReadOnboardingVideoResponse.__pydantic_serializer__.to_json(
                ReadOnboardingVideoResponse(
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


async def raw_read_onboarding_videos(
    itgs: Itgs,
    filters_to_apply: List[Tuple[str, FilterItemLike]],
    sort: List[SortItem],
    limit: int,
):
    """performs exactly the specified sort without pagination logic"""
    onboarding_videos = Table("onboarding_videos")
    image_files = Table("image_files")
    content_files = Table("content_files")

    query: QueryBuilder = (
        Query.from_(onboarding_videos)
        .select(
            onboarding_videos.uid,
            onboarding_videos.purpose,
            content_files.uid,
            image_files.uid,
            onboarding_videos.active_at,
            onboarding_videos.visible_in_admin,
            onboarding_videos.created_at,
        )
        .join(content_files)
        .on(content_files.id == onboarding_videos.video_content_file_id)
        .join(image_files)
        .on(image_files.id == onboarding_videos.thumbnail_image_file_id)
    )
    qargs = []

    def pseudocolumn(key: str) -> Term:
        if key == "uid":
            return onboarding_videos.field("uid")
        elif key == "purpose_type":
            return Function(
                "json_extract", onboarding_videos.field("purpose"), "$.type"
            )
        elif key == "purpose":
            return onboarding_videos.field("purpose")
        elif key == "video_content_file_uid":
            return content_files.field("uid")
        elif key == "video_content_file_original_sha512":
            return content_files.field("original_sha512")
        elif key == "thumbnail_image_file_uid":
            return image_files.field("uid")
        elif key == "thumbnail_image_file_original_sha512":
            return image_files.field("original_sha512")
        elif key == "active_at":
            return onboarding_videos.field("active_at")
        elif key == "visible_in_admin":
            return onboarding_videos.field("visible_in_admin")
        elif key == "created_at":
            return onboarding_videos.field("created_at")
        raise ValueError(f"Unknown key {key}")

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
    items: List[InternalOnboardingVideo] = []
    for row in response.results or []:
        items.append(
            await parse_internal_onboarding_video_row(
                itgs, row=InternalOnboardingVideoRow(*row)
            )
        )
    return items


def item_pseudocolumns(item: InternalOnboardingVideo) -> dict:
    """returns the dictified item such that the keys in the return dict match
    the keys of the sort options"""
    return {
        "uid": item.uid,
        "purpose_type": item.purpose.type,
        "created_at": item.created_at,
    }
