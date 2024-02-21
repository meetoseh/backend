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
import content_files.auth as content_files_auth
from content_files.models import ContentFileRef


class CourseVideo(BaseModel):
    uid: str = Field(description="The primary stable external identifier for this row")
    content_file: ContentFileRef = Field(description="The underlying content file")
    content_file_original_sha512: str = Field(
        description="The sha512 of the original file processed to make the video"
    )
    content_file_created_at: float = Field(
        description="When the content file was originally uploaded, in seconds since the epoch"
    )
    uploaded_by_user_sub: Optional[str] = Field(
        description="The sub of the user who originally uplaoded this file, if available"
    )
    last_uploaded_at: float = Field(
        description="the last time this file was uploaded, in seconds since the epoch"
    )


COURSE_VIDEO_SORT_OPTIONS = [
    SortItem[Literal["uid"], str],
    SortItem[Literal["content_file_created_at"], float],
    SortItem[Literal["last_uploaded_at"], float],
]
CourseVideoSortOption = Union[
    SortItemModel[Literal["uid"], str],
    SortItemModel[Literal["content_file_created_at"], float],
    SortItemModel[Literal["last_uploaded_at"], float],
]


class CourseVideoFilter(BaseModel):
    uid: Optional[FilterTextItemModel] = Field(
        None, description="the uid of the course video row"
    )
    content_file_uid: Optional[FilterTextItemModel] = Field(
        None, description="the uid of the content file"
    )
    original_file_sha512: Optional[FilterTextItemModel] = Field(
        None, description="the sha512 of the original file"
    )
    uploaded_by_user_sub: Optional[FilterTextItemModel] = Field(
        None, description="the sub of the user who uploaded the file"
    )
    last_uploaded_at: Optional[FilterItemModel[float]] = Field(
        None, description="the last time the file was uploaded"
    )


class ReadCourseVideoRequest(BaseModel):
    filters: CourseVideoFilter = Field(
        default_factory=lambda: CourseVideoFilter.model_validate({}),
        description="the filters to apply",
    )
    sort: Optional[List[CourseVideoSortOption]] = Field(
        None, description="the sort order to apply"
    )
    limit: int = Field(
        25, description="the maximum number of rows to return", ge=1, le=250
    )


class ReadCourseVideoResponse(BaseModel):
    items: List[CourseVideo] = Field(
        description="the items matching the filters in the given sort"
    )
    next_page_sort: Optional[List[CourseVideoSortOption]] = Field(
        None, description="if there is a next or earlier page, the sort order to get it"
    )


router = APIRouter()


@router.post(
    "/search", response_model=ReadCourseVideoResponse, responses=STANDARD_ERRORS_BY_CODE
)
async def read_course_videos(
    args: ReadCourseVideoRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Lists out course videos

    This requires standard authorization for a user with admin access
    """
    sort = [srt.to_result() for srt in (args.sort or [])]
    sort = cleanup_sort(COURSE_VIDEO_SORT_OPTIONS, sort, ["uid"])
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
        items = await raw_read_course_videos(
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
            rev_items = await raw_read_course_videos(
                itgs, filters_to_apply, rev_sort, 1
            )
            if rev_items:
                first_item = item_pseudocolumns(items[0])

        if first_item is not None or last_item is not None:
            next_page_sort = get_next_page_sort(first_item, last_item, sort)

        return Response(
            content=ReadCourseVideoResponse.__pydantic_serializer__.to_json(
                ReadCourseVideoResponse(
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


async def raw_read_course_videos(
    itgs: Itgs,
    filters_to_apply: List[Tuple[str, FilterItemLike]],
    sort: List[SortItem],
    limit: int,
) -> List[CourseVideo]:
    """performs exactly the specified sort without pagination logic"""
    course_videos = Table("course_videos")
    content_files = Table("content_files")
    users = Table("users")

    query: QueryBuilder = (
        Query.from_(course_videos)
        .select(
            course_videos.uid,
            content_files.uid,
            content_files.original_sha512,
            content_files.created_at,
            users.sub,
            course_videos.last_uploaded_at,
        )
        .join(content_files)
        .on(content_files.id == course_videos.content_file_id)
        .left_outer_join(users)
        .on(users.id == course_videos.uploaded_by_user_id)
    )
    qargs = []

    def pseudocolumn(key: str) -> Term:
        if key == "uid":
            return course_videos.field("uid")
        elif key == "content_file_created_at":
            return content_files.field("created_at")
        elif key == "original_file_sha512":
            return content_files.field("original_sha512")
        elif key == "uploaded_by_user_sub":
            return users.field("sub")
        elif key == "last_uploaded_at":
            return course_videos.field("last_uploaded_at")
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
    items: List[CourseVideo] = []
    for row in response.results or []:
        items.append(
            CourseVideo(
                uid=row[0],
                content_file=ContentFileRef(
                    uid=row[1], jwt=await content_files_auth.create_jwt(itgs, row[1])
                ),
                content_file_original_sha512=row[2],
                content_file_created_at=row[3],
                uploaded_by_user_sub=row[4],
                last_uploaded_at=row[5],
            )
        )
    return items


def item_pseudocolumns(item: CourseVideo) -> dict:
    """returns the dictified item such that the keys in the return dict match
    the keys of the sort options"""
    return {
        "uid": item.uid,
        "content_file_created_at": item.content_file_created_at,
        "last_uploaded_at": item.last_uploaded_at,
    }
