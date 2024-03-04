from pypika import Table, Query, Parameter
from pypika.queries import QueryBuilder
from pypika.terms import Term, Function, Case
from typing import Annotated, Any, Dict, List, Literal, Optional, Tuple, Union, cast
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, TypeAdapter
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


class CourseVideoThumbnailUserSource(BaseModel):
    type: Literal["user"] = Field(
        description="Indicates this thumbnail was uploaded by a user"
    )
    sub: str = Field(description="The sub of the user who uploaded the thumbnail")


class CourseVideoThumbnailFrameSource(BaseModel):
    type: Literal["frame"] = Field(
        description="Indicates this thumbnail was generated from a frame"
    )
    frame_number: int = Field(
        description="The frame number from which this thumbnail was generated, where 1 is the first frame"
    )
    video_sha512: str = Field(
        description="The original sha512 of the content file this thumbnail was for"
    )
    via_sha512: str = Field(
        description=(
            "The sha512 of the video the frame was actually extracted from, "
            "which might be one of the exports rather than the original video"
        )
    )


CourseVideoThumbnailSource = Union[
    CourseVideoThumbnailUserSource, CourseVideoThumbnailFrameSource
]

source_validator = TypeAdapter(CourseVideoThumbnailSource)


class CourseVideoThumbnail(BaseModel):
    uid: str = Field(description="The primary stable external identifier for this row")
    source: CourseVideoThumbnailSource = Field(
        description="The source of the thumbnail"
    )
    image_file: ImageFileRef = Field(description="The underlying image file")
    image_file_created_at: float = Field(
        description="When the image file was originally uploaded, in seconds since the epoch"
    )
    last_uploaded_at: float = Field(
        description="the last time this file was uploaded, in seconds since the epoch"
    )


COURSE_VIDEO_THUMBNAIL_SORT_OPTIONS = [
    SortItem[Literal["uid"], str],
    SortItem[Literal["image_file_created_at"], float],
    SortItem[Literal["source_type"], str],
    SortItem[Literal["source_frame_number"], int],
    SortItem[Literal["last_uploaded_at"], float],
]
CourseVideoThumbnailSortOption = Union[
    SortItemModel[Literal["uid"], str],
    SortItemModel[Literal["image_file_created_at"], float],
    SortItemModel[Literal["source_type"], str],
    SortItemModel[Literal["source_frame_number"], int],
    SortItemModel[Literal["last_uploaded_at"], float],
]


class CourseVideoThumbnailFilter(BaseModel):
    uid: Optional[FilterTextItemModel] = Field(
        None, description="the uid of the course video thumbnail row"
    )
    image_file_uid: Optional[FilterTextItemModel] = Field(
        None, description="the uid of the image file"
    )
    original_file_sha512: Optional[FilterTextItemModel] = Field(
        None, description="the sha512 of the original version of the thumbnail"
    )
    source_type: Optional[FilterTextItemModel] = Field(
        None, description="the type of the source of the thumbnail"
    )
    source_sub: Optional[FilterTextItemModel] = Field(
        None,
        description="the sub of the user who uploaded the thumbnail, if the source type is user, otherwise null",
    )
    source_video_sha512: Optional[FilterTextItemModel] = Field(
        None,
        description="the sha512 of the video the frame was for, if the source type is frame, otherwise null",
    )
    last_uploaded_at: Optional[FilterItemModel[float]] = Field(
        None, description="the last time the file was uploaded"
    )


class ReadCourseVideoThumbnailRequest(BaseModel):
    filters: CourseVideoThumbnailFilter = Field(
        default_factory=lambda: CourseVideoThumbnailFilter.model_validate({}),
        description="the filters to apply",
    )
    sort: Optional[List[CourseVideoThumbnailSortOption]] = Field(
        None, description="the sort order to apply"
    )
    limit: int = Field(
        25, description="the maximum number of rows to return", ge=1, le=250
    )


class ReadCourseVideoThumbnailResponse(BaseModel):
    items: List[CourseVideoThumbnail] = Field(
        description="the items matching the filters in the given sort"
    )
    next_page_sort: Optional[List[CourseVideoThumbnailSortOption]] = Field(
        None, description="if there is a next or earlier page, the sort order to get it"
    )


router = APIRouter()


@router.post(
    "/search",
    response_model=ReadCourseVideoThumbnailResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_course_video_thumbnails(
    args: ReadCourseVideoThumbnailRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Lists out course video thumbnails

    This requires standard authorization for a user with admin access
    """
    sort = [srt.to_result() for srt in (args.sort or [])]
    sort = cleanup_sort(COURSE_VIDEO_THUMBNAIL_SORT_OPTIONS, sort, ["uid"])
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
        items = await raw_read_course_video_thumbnails(
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
            rev_items = await raw_read_course_video_thumbnails(
                itgs, filters_to_apply, rev_sort, 1
            )
            if rev_items:
                first_item = item_pseudocolumns(items[0])

        if first_item is not None or last_item is not None:
            next_page_sort = get_next_page_sort(first_item, last_item, sort)

        return Response(
            content=ReadCourseVideoThumbnailResponse.__pydantic_serializer__.to_json(
                ReadCourseVideoThumbnailResponse(
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


async def raw_read_course_video_thumbnails(
    itgs: Itgs,
    filters_to_apply: List[Tuple[str, FilterItemLike]],
    sort: List[SortItem],
    limit: int,
) -> List[CourseVideoThumbnail]:
    """performs exactly the specified sort without pagination logic"""
    course_video_thumbnail_images = Table("course_video_thumbnail_images")
    image_files = Table("image_files")

    query: QueryBuilder = (
        Query.from_(course_video_thumbnail_images)
        .select(
            course_video_thumbnail_images.uid,
            course_video_thumbnail_images.source,
            image_files.uid,
            image_files.created_at,
            course_video_thumbnail_images.last_uploaded_at,
        )
        .join(image_files)
        .on(image_files.id == course_video_thumbnail_images.image_file_id)
    )
    qargs = []

    def pseudocolumn(key: str) -> Term:
        if key == "uid":
            return course_video_thumbnail_images.field("uid")
        elif key == "image_file_created_at":
            return image_files.field("created_at")
        elif key == "source_type":
            return Function(
                "json_extract", course_video_thumbnail_images.field("source"), "$.type"
            )
        elif key == "source_frame_number":
            return Function(
                "json_extract",
                course_video_thumbnail_images.field("source"),
                "$.frame_number",
            )
        elif key == "last_uploaded_at":
            return course_video_thumbnail_images.field("last_uploaded_at")
        elif key == "image_file_uid":
            return image_files.field("uid")
        elif key == "original_file_sha512":
            return image_files.field("original_sha512")
        elif key == "source_sub":
            # the Case allows use of the conditioned index
            return (
                Case()
                .when(
                    Function(
                        "json_extract",
                        course_video_thumbnail_images.field("source"),
                        "$.type",
                    )
                    == "user",
                    Function(
                        "json_extract",
                        course_video_thumbnail_images.field("source"),
                        "$.sub",
                    ),
                )
                .else_(None)
            )
        elif key == "source_video_sha512":
            # the Case allows use of the conditioned index
            return (
                Case()
                .when(
                    Function(
                        "json_extract",
                        course_video_thumbnail_images.field("source"),
                        "$.type",
                    )
                    == "frame",
                    Function(
                        "json_extract",
                        course_video_thumbnail_images.field("source"),
                        "$.video_sha512",
                    ),
                )
                .else_(None)
            )

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
    items: List[CourseVideoThumbnail] = []
    for row in response.results or []:
        items.append(
            CourseVideoThumbnail(
                uid=row[0],
                source=source_validator.validate_json(row[1]),
                image_file=ImageFileRef(
                    uid=row[2], jwt=await image_files_auth.create_jwt(itgs, row[2])
                ),
                image_file_created_at=row[3],
                last_uploaded_at=row[4],
            )
        )
    return items


def item_pseudocolumns(item: CourseVideoThumbnail) -> dict:
    """returns the dictified item such that the keys in the return dict match
    the keys of the sort options"""
    return {
        "uid": item.uid,
        "image_file_created_at": item.image_file_created_at,
        "source_type": item.source.type,
        "source_frame_number": (
            item.source.frame_number if item.source.type == "frame" else None
        ),
        "last_uploaded_at": item.last_uploaded_at,
    }
