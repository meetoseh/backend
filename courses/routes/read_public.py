from pypika import Table, Query, Parameter
from pypika.queries import QueryBuilder
from pypika.functions import Count, Star, Coalesce
from pypika.terms import Term
from typing import (
    Annotated,
    Any,
    Dict,
    List,
    Literal,
    Optional,
    Set,
    Tuple,
    Union,
    cast,
)
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from auth import auth_any
from courses.lib.get_external_course_from_row import (
    ExternalCourseRow,
    get_external_course_from_row,
)
from courses.models.external_course import ExternalCourse
from journeys.models.series_flags import SeriesFlags
from models import STANDARD_ERRORS_BY_CODE
from resources.filter import sort_criterion, flattened_filters
from resources.filter_item import FilterItemModel
from resources.filter_item_like import FilterItemLike
from resources.sort import cleanup_sort, get_next_page_sort, reverse_sort
from resources.sort_item import SortItem, SortItemModel
from resources.filter_text_item import FilterTextItemModel
from itgs import Itgs
import users.lib.entitlements as user_entitlements


EXTERNAL_COURSE_SORT_OPTIONS = [
    SortItem[Literal["uid"], str],
    SortItem[Literal["slug"], str],
    SortItem[Literal["title"], str],
    SortItem[Literal["liked_at"], float],
    SortItem[Literal["joined_at"], float],
    SortItem[Literal["instructor_name"], str],
    SortItem[Literal["created_at"], float],
]
ExternalCourseSortOption = Union[
    SortItemModel[Literal["uid"], str],
    SortItemModel[Literal["slug"], str],
    SortItemModel[Literal["title"], str],
    SortItemModel[Literal["liked_at"], float],
    SortItemModel[Literal["joined_at"], float],
    SortItemModel[Literal["instructor_name"], str],
    SortItemModel[Literal["created_at"], float],
]


class ExternalCourseFilter(BaseModel):
    uid: Optional[FilterTextItemModel] = Field(
        None, description="the uid of the course row"
    )
    slug: Optional[FilterTextItemModel] = Field(
        None, description="the slug of the course row"
    )
    title: Optional[FilterTextItemModel] = Field(
        None, description="the title of the course"
    )
    instructor_uid: Optional[FilterTextItemModel] = Field(
        None, description="the uid of the instructor for the course"
    )
    instructor_name: Optional[FilterTextItemModel] = Field(
        None, description="the name of the instructor for the course"
    )
    revenue_cat_entitlement: Optional[FilterTextItemModel] = Field(
        None, description="the RevenueCat entitlement required for the course"
    )
    liked_at: Optional[FilterItemModel[float]] = Field(
        None,
        description="the time the user liked the course, in seconds since the epoch",
    )
    joined_at: Optional[FilterItemModel[float]] = Field(
        None,
        description="the time the user joined the course, in seconds since the epoch",
    )
    created_at: Optional[FilterItemModel[float]] = Field(
        None, description="the time the course was created, in seconds since the epoch"
    )


class ReadExternalCourseRequest(BaseModel):
    filters: ExternalCourseFilter = Field(
        default_factory=lambda: ExternalCourseFilter.model_validate({}),
        description="the filters to apply",
    )
    sort: Optional[List[ExternalCourseSortOption]] = Field(
        None, description="the sort order to apply"
    )
    limit: int = Field(
        5, description="the maximum number of rows to return", ge=1, le=50
    )


class ReadExternalCourseResponse(BaseModel):
    items: List[ExternalCourse] = Field(
        description="the items matching the filters in the given sort"
    )
    next_page_sort: Optional[List[ExternalCourseSortOption]] = Field(
        None, description="if there is a next or earlier page, the sort order to get it"
    )


router = APIRouter()


@router.post(
    "/search_public",
    response_model=ReadExternalCourseResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_external_courses(
    args: ReadExternalCourseRequest,
    category: Literal["list", "library"],
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Lists out courses from the authorized users perspective, either
    filtered to those in the public series list (category=list) or those that
    would go in the their "My Library" under the "Series" tab (category=library).

    This requires standard authorization
    """
    sort = [srt.to_result() for srt in (args.sort or [])]
    sort = cleanup_sort(EXTERNAL_COURSE_SORT_OPTIONS, sort, ["uid", "slug"])
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response
        filters_to_apply = flattened_filters(
            dict(
                (k, cast(FilterItemLike, v.to_result()))
                for k, v in args.filters.__dict__.items()
                if v is not None
            )
        )
        items = await raw_read_external_courses(
            itgs,
            filters_to_apply,
            sort,
            args.limit + 1,
            category=category,
            user_sub=auth_result.result.sub,
        )
        next_page_sort: Optional[List[SortItem]] = None
        last_item: Optional[Dict[str, Any]] = None
        if len(items) > args.limit:
            items = items[: args.limit]
            last_item = item_pseudocolumns(items[-1])
        first_item: Optional[Dict[str, Any]] = None
        if items and any(s.after is not None for s in sort):
            rev_sort = reverse_sort(sort, "make_exclusive")
            rev_items = await raw_read_external_courses(
                itgs,
                filters_to_apply,
                rev_sort,
                1,
                category=category,
                user_sub=auth_result.result.sub,
            )
            if rev_items:
                first_item = item_pseudocolumns(items[0])

        if first_item is not None or last_item is not None:
            next_page_sort = get_next_page_sort(first_item, last_item, sort)

        return Response(
            content=ReadExternalCourseResponse.__pydantic_serializer__.to_json(
                ReadExternalCourseResponse(
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


async def raw_read_external_courses(
    itgs: Itgs,
    filters_to_apply: List[Tuple[str, FilterItemLike]],
    sort: List[SortItem],
    limit: int,
    /,
    *,
    category: Literal["list", "library"],
    user_sub: str,
) -> List[ExternalCourse]:
    """performs exactly the specified sort without pagination logic"""
    users = Table("users")
    courses = Table("courses")
    course_journeys = Table("course_journeys")
    course_num_journeys = Table("course_num_journeys")
    instructors = Table("instructors")
    image_files = Table("image_files")
    course_darkened_background_images = image_files.as_("cdbi")
    course_logo_images = image_files.as_("cli")
    course_users = Table("course_users")
    user_course_likes = Table("user_course_likes")
    content_files = Table("content_files")
    intro_videos = content_files.as_("intro_videos")
    content_file_transcripts = Table("content_file_transcripts")
    intro_content_file_transcripts = content_file_transcripts.as_("icft")
    transcripts = Table("transcripts")
    intro_video_transcripts = transcripts.as_("intro_video_transcripts")
    intro_video_thumbnails = image_files.as_("intro_video_thumbnails")

    query: QueryBuilder = (
        Query.with_(
            Query.from_(course_journeys)
            .select(
                course_journeys.course_id.as_("course_id"),
                Count(Star()).as_("num_journeys"),
            )
            .groupby(course_journeys.course_id),
            "course_num_journeys",
        )
        .from_(courses)
        .select(
            courses.uid,
            courses.slug,
            courses.title,
            courses.description,
            instructors.uid,
            instructors.name,
            course_darkened_background_images.uid,
            course_logo_images.uid,
            courses.revenue_cat_entitlement,
            course_users.created_at,
            user_course_likes.created_at,
            courses.created_at,
            Coalesce(course_num_journeys.num_journeys, 0),
            intro_videos.uid,
            intro_videos.duration_seconds,
            intro_video_transcripts.uid,
            intro_video_thumbnails.uid,
        )
        .join(users)
        .on(users.sub == Parameter("?"))
        .join(instructors)
        .on(instructors.id == courses.instructor_id)
        .join(course_darkened_background_images)
        .on(
            course_darkened_background_images.id
            == courses.background_darkened_image_file_id
        )
        .left_outer_join(course_logo_images)
        .on(course_logo_images.id == courses.logo_image_file_id)
        .left_outer_join(course_num_journeys)
        .on(course_num_journeys.course_id == courses.id)
        .left_outer_join(course_users)
        .on((course_users.course_id == courses.id) & (course_users.user_id == users.id))
        .left_outer_join(user_course_likes)
        .on(
            (user_course_likes.course_id == courses.id)
            & (user_course_likes.user_id == users.id)
        )
        .left_outer_join(intro_videos)
        .on(intro_videos.id == courses.video_content_file_id)
        .left_outer_join(intro_content_file_transcripts)
        .on(
            intro_content_file_transcripts.content_file_id
            == courses.video_content_file_id
        )
        .left_outer_join(intro_video_transcripts)
        .on(intro_video_transcripts.id == intro_content_file_transcripts.transcript_id)
        .left_outer_join(intro_video_thumbnails)
        .on(intro_video_thumbnails.id == courses.video_thumbnail_image_file_id)
    )
    qargs: List[Any] = [user_sub]

    if category == "library":
        query = query.where(course_users.field("id").notnull())
        query = query.where(
            courses.field("flags").bitwiseand(SeriesFlags.SERIES_VISIBLE_IN_OWNED) != 0
        )
    elif category == "list":
        query = query.where(
            courses.field("flags").bitwiseand(SeriesFlags.SERIES_IN_SERIES_TAB) != 0
        )
    else:
        raise ValueError(f"Unknown category {category}")

    def pseudocolumn(key: str) -> Term:
        if key in (
            "uid",
            "slug",
            "title",
            "revenue_cat_entitlement",
            "created_at",
        ):
            return courses.field(key)
        elif key == "instructor_uid":
            return instructors.field("uid")
        elif key == "instructor_name":
            return instructors.field("name")
        elif key == "liked_at":
            return user_course_likes.field("created_at")
        elif key == "joined_at":
            return course_users.field("created_at")

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
    items: List[ExternalCourse] = []
    for row in response.results or []:
        # we don't pass the user_sub to reduce calls to the entitlements service
        items.append(
            await get_external_course_from_row(
                itgs, row=ExternalCourseRow(*row), user_sub=None
            )
        )

    relevant_entitlements = list(set(item.revenue_cat_entitlement for item in items))
    if relevant_entitlements:
        # PERF:
        #   due to how the cache is currently constructed its faster not to gather here;
        #   we should fix this in the users.lib.entitlements module
        #
        #   specifically, if we gather and the cache is empty we will stampede the requests
        #   instead of automatically delaying until the first result and reusing the result
        #   for the rest
        entitlements_result = [
            await user_entitlements.get_entitlement(
                itgs, user_sub=user_sub, identifier=ent
            )
            for ent in relevant_entitlements
        ]
        have_entitlements: Set[str] = set()
        for ent, result in zip(relevant_entitlements, entitlements_result):
            if result is not None and result.is_active:
                have_entitlements.add(ent)
        for item in items:
            item.has_entitlement = item.revenue_cat_entitlement in have_entitlements

    return items


def item_pseudocolumns(item: ExternalCourse) -> dict:
    """returns the dictified item such that the keys in the return dict match
    the keys of the sort options"""
    return {
        "uid": item.uid,
        "slug": item.slug,
        "title": item.title,
        "liked_at": item.liked_at,
        "joined_at": item.joined_at,
        "instructor_name": item.instructor.name,
        "created_at": item.created_at,
    }
