from pypika import Table, Query, Parameter
from pypika.queries import QueryBuilder
from pypika.terms import Term
from typing import Annotated, Any, Dict, List, Literal, Optional, Tuple, Union, cast
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from auth import auth_admin
from courses.models.internal_course import InternalCourse, InternalCourseInstructor
from models import STANDARD_ERRORS_BY_CODE
from resources.filter import sort_criterion, flattened_filters
from resources.filter_bit_field_item import FilterBitFieldItemModel
from resources.filter_item import FilterItemModel
from resources.filter_item_like import FilterItemLike
from resources.sort import cleanup_sort, get_next_page_sort, reverse_sort
from resources.sort_item import SortItem, SortItemModel
from resources.filter_text_item import FilterTextItemModel
from itgs import Itgs
import image_files.auth as image_files_auth
from image_files.models import ImageFileRef
import content_files.auth as content_files_auth
from content_files.models import ContentFileRef


COURSE_SORT_OPTIONS = [
    SortItem[Literal["uid"], str],
    SortItem[Literal["slug"], str],
    SortItem[Literal["title"], str],
    SortItem[Literal["instructor_name"], str],
    SortItem[Literal["created_at"], float],
]
CourseSortOption = Union[
    SortItemModel[Literal["uid"], str],
    SortItemModel[Literal["slug"], str],
    SortItemModel[Literal["title"], str],
    SortItemModel[Literal["instructor_name"], str],
    SortItemModel[Literal["created_at"], float],
]


class CourseFilter(BaseModel):
    uid: Optional[FilterTextItemModel] = Field(
        None, description="the uid of the course row"
    )
    slug: Optional[FilterTextItemModel] = Field(
        None, description="the slug of the course row"
    )
    flags: Optional[FilterBitFieldItemModel] = Field(
        None, description="the access flags for the course"
    )
    revenue_cat_entitlement: Optional[FilterTextItemModel] = Field(
        None, description="the entitlement name required for this course"
    )
    title: Optional[FilterTextItemModel] = Field(
        None, description="the title of the course"
    )
    description: Optional[FilterTextItemModel] = Field(
        None, description="the description of the course"
    )
    instructor_uid: Optional[FilterTextItemModel] = Field(
        None, description="the uid of the instructor for the course"
    )
    instructor_name: Optional[FilterTextItemModel] = Field(
        None, description="the name of the instructor for the course"
    )
    background_original_sha512: Optional[FilterTextItemModel] = Field(
        None, description="the sha512 of the original background image"
    )
    background_original_image_uid: Optional[FilterTextItemModel] = Field(
        None, description="the uid of the image file for the original background image"
    )
    video_original_sha512: Optional[FilterTextItemModel] = Field(
        None, description="the sha512 of the original video content"
    )
    video_content_uid: Optional[FilterTextItemModel] = Field(
        None, description="the uid of the content file for the video content"
    )
    logo_original_sha512: Optional[FilterTextItemModel] = Field(
        None, description="the sha512 of the original logo image"
    )
    logo_image_uid: Optional[FilterTextItemModel] = Field(
        None, description="the uid of the image file for the logo image"
    )
    hero_original_sha512: Optional[FilterTextItemModel] = Field(
        None, description="the sha512 of the original hero image"
    )
    hero_image_uid: Optional[FilterTextItemModel] = Field(
        None, description="the uid of the image file for the hero image"
    )
    video_thumbnail_image_uid: Optional[FilterTextItemModel] = Field(
        None, description="the uid of the image file for the video thumbnail image"
    )
    created_at: Optional[FilterItemModel[float]] = Field(
        None, description="the time the course was created, in seconds since the epoch"
    )


class ReadCourseRequest(BaseModel):
    filters: CourseFilter = Field(
        default_factory=lambda: CourseFilter.model_validate({}),
        description="the filters to apply",
    )
    sort: Optional[List[CourseSortOption]] = Field(
        None, description="the sort order to apply"
    )
    limit: int = Field(
        5, description="the maximum number of rows to return", ge=1, le=50
    )


class ReadCourseResponse(BaseModel):
    items: List[InternalCourse] = Field(
        description="the items matching the filters in the given sort"
    )
    next_page_sort: Optional[List[CourseSortOption]] = Field(
        None, description="if there is a next or earlier page, the sort order to get it"
    )


router = APIRouter()


@router.post(
    "/search",
    response_model=ReadCourseResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_courses(
    args: ReadCourseRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Lists out courses

    This requires standard authorization for a user with admin access
    """
    sort = [srt.to_result() for srt in (args.sort or [])]
    sort = cleanup_sort(COURSE_SORT_OPTIONS, sort, ["uid"])
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
        items = await raw_read_courses(itgs, filters_to_apply, sort, args.limit + 1)
        next_page_sort: Optional[List[SortItem]] = None
        last_item: Optional[Dict[str, Any]] = None
        if len(items) > args.limit:
            items = items[: args.limit]
            last_item = item_pseudocolumns(items[-1])
        first_item: Optional[Dict[str, Any]] = None
        if items and any(s.after is not None for s in sort):
            rev_sort = reverse_sort(sort, "make_exclusive")
            rev_items = await raw_read_courses(itgs, filters_to_apply, rev_sort, 1)
            if rev_items:
                first_item = item_pseudocolumns(items[0])

        if first_item is not None or last_item is not None:
            next_page_sort = get_next_page_sort(first_item, last_item, sort)

        return Response(
            content=ReadCourseResponse.__pydantic_serializer__.to_json(
                ReadCourseResponse(
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


async def raw_read_courses(
    itgs: Itgs,
    filters_to_apply: List[Tuple[str, FilterItemLike]],
    sort: List[SortItem],
    limit: int,
) -> List[InternalCourse]:
    """performs exactly the specified sort without pagination logic"""
    courses = Table("courses")
    instructors = Table("instructors")
    image_files = Table("image_files")
    instructor_pictures = cast(Table, image_files.as_("instructor_pictures"))
    background_original_image_files = cast(
        Table, image_files.as_("background_original_image_files")
    )
    background_darkened_image_files = cast(
        Table, image_files.as_("background_darkened_image_files")
    )
    content_files = Table("content_files")
    video_content_files = cast(Table, content_files.as_("video_content_files"))
    video_thumbnail_image_files = cast(
        Table, image_files.as_("video_thumbnail_image_files")
    )
    logo_image_files = cast(Table, image_files.as_("logo_image_files"))
    hero_image_files = cast(Table, image_files.as_("hero_image_files"))

    query: QueryBuilder = (
        Query.from_(courses)
        .select(
            courses.uid,
            courses.slug,
            courses.flags,
            courses.revenue_cat_entitlement,
            courses.title,
            courses.description,
            instructors.uid,
            instructors.name,
            instructor_pictures.uid,
            background_original_image_files.uid,
            background_darkened_image_files.uid,
            video_content_files.uid,
            video_thumbnail_image_files.uid,
            logo_image_files.uid,
            hero_image_files.uid,
            courses.created_at,
        )
        .join(instructors)
        .on(instructors.id == courses.instructor_id)
        .left_join(instructor_pictures)
        .on(instructor_pictures.id == instructors.picture_image_file_id)
        .left_join(background_original_image_files)
        .on(
            background_original_image_files.id
            == courses.background_original_image_file_id
        )
        .left_join(background_darkened_image_files)
        .on(
            background_darkened_image_files.id
            == courses.background_darkened_image_file_id
        )
        .left_join(video_content_files)
        .on(video_content_files.id == courses.video_content_file_id)
        .left_join(video_thumbnail_image_files)
        .on(video_thumbnail_image_files.id == courses.video_thumbnail_image_file_id)
        .left_join(logo_image_files)
        .on(logo_image_files.id == courses.logo_image_file_id)
        .left_join(hero_image_files)
        .on(hero_image_files.id == courses.hero_image_file_id)
    )
    qargs = []

    def pseudocolumn(key: str) -> Term:
        if key in (
            "uid",
            "slug",
            "flags",
            "revenue_cat_entitlement",
            "title",
            "description",
            "created_at",
        ):
            return courses.field(key)
        elif key == "instructor_uid":
            return instructors.field("uid")
        elif key == "instructor_name":
            return instructors.field("name")
        elif key == "background_original_sha512":
            return background_original_image_files.field("original_sha512")
        elif key == "background_original_image_uid":
            return background_original_image_files.field("uid")
        elif key == "video_original_sha512":
            return video_content_files.field("original_sha512")
        elif key == "video_content_uid":
            return video_content_files.field("uid")
        elif key == "logo_original_sha512":
            return logo_image_files.field("original_sha512")
        elif key == "logo_image_uid":
            return logo_image_files.field("uid")
        elif key == "hero_original_sha512":
            return hero_image_files.field("original_sha512")
        elif key == "hero_image_uid":
            return hero_image_files.field("uid")
        elif key == "video_thumbnail_image_uid":
            return video_thumbnail_image_files.field("uid")

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
    items: List[InternalCourse] = []
    for row in response.results or []:
        items.append(
            InternalCourse(
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
                        ImageFileRef(
                            uid=row[8],
                            jwt=await image_files_auth.create_jwt(itgs, row[8]),
                        )
                        if row[8] is not None
                        else None
                    ),
                ),
                background_original_image=(
                    ImageFileRef(
                        uid=row[9], jwt=await image_files_auth.create_jwt(itgs, row[9])
                    )
                    if row[9] is not None
                    else None
                ),
                background_darkened_image=(
                    ImageFileRef(
                        uid=row[10],
                        jwt=await image_files_auth.create_jwt(itgs, row[10]),
                    )
                    if row[10] is not None
                    else None
                ),
                video_content=(
                    ContentFileRef(
                        uid=row[11],
                        jwt=await content_files_auth.create_jwt(itgs, row[11]),
                    )
                    if row[11] is not None
                    else None
                ),
                video_thumbnail=(
                    ImageFileRef(
                        uid=row[12],
                        jwt=await image_files_auth.create_jwt(itgs, row[12]),
                    )
                    if row[12] is not None
                    else None
                ),
                logo_image=(
                    ImageFileRef(
                        uid=row[13],
                        jwt=await image_files_auth.create_jwt(itgs, row[13]),
                    )
                    if row[13] is not None
                    else None
                ),
                hero_image=(
                    ImageFileRef(
                        uid=row[14],
                        jwt=await image_files_auth.create_jwt(itgs, row[14]),
                    )
                    if row[14] is not None
                    else None
                ),
                created_at=row[15],
            )
        )
    return items


def item_pseudocolumns(item: InternalCourse) -> dict:
    """returns the dictified item such that the keys in the return dict match
    the keys of the sort options"""
    return {
        "uid": item.uid,
        "slug": item.slug,
        "title": item.title,
        "instructor_name": item.instructor.name,
        "created_at": item.created_at,
    }
