import json
import time
from pypika import Table, Query, Parameter, Not
from pypika.queries import QueryBuilder
from pypika.functions import Count, Star, Coalesce
from pypika.terms import Term, ExistsCriterion
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
from models import AUTHORIZATION_UNKNOWN_TOKEN, STANDARD_ERRORS_BY_CODE
from resources.filter import sort_criterion, flattened_filters
from resources.filter_item import FilterItemModel
from resources.filter_item_like import FilterItemLike
from resources.sort import cleanup_sort, get_next_page_sort, reverse_sort
from resources.sort_item import SortItem, SortItemModel
from resources.filter_text_item import FilterTextItemModel
from itgs import Itgs
from resources.standard_text_operator import StandardTextOperator
import users.lib.entitlements as user_entitlements
import courses.auth as courses_auth


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
    category: Optional[Literal["list", "library"]] = None,
    course_jwt: Optional[str] = None,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Lists out courses from the authorized users perspective, either
    filtered to those in the public series list (category=list) or those that
    would go in the their "My Library" under the "Series" tab (category=library).
    If the category is not specified then a course JWT must be specified.

    If a course JWT is specified, the category is ignored and the course uid
    filter is ignored. Instead, a 403 is returned unless the course JWT is valid
    and has the VIEW_METADATA flag, and the course uid filter is set to the
    course uid from the JWT. Furthermore, the returned JWTs have the same expiration
    time and access flags as the input JWT.

    This requires standard authorization.
    """
    using_course_jwt = course_jwt is not None
    if not using_course_jwt and category is None:
        return Response(
            content=json.dumps(
                {
                    "detail": [
                        {
                            "loc": ["query", "category"],
                            "msg": "required if course_jwt is not specified",
                            "type": "value_error",
                        }
                    ]
                }
            ),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=422,
        )

    sort = [srt.to_result() for srt in (args.sort or [])]
    sort = cleanup_sort(EXTERNAL_COURSE_SORT_OPTIONS, sort, ["uid", "slug"])
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        course_auth_result = None
        jwt_expires_at = int(time.time() + 1800)
        jwt_no_entitlement_access_flags = (
            courses_auth.CourseAccessFlags.VIEW_METADATA
            | courses_auth.CourseAccessFlags.LIKE
        )
        jwt_has_entitlement_access_flags = (
            jwt_no_entitlement_access_flags
            | courses_auth.CourseAccessFlags.TAKE_JOURNEYS
        )
        if using_course_jwt:
            course_auth_result = await courses_auth.auth_any(
                itgs, f"bearer {course_jwt}"
            )
            if course_auth_result.result is None:
                return course_auth_result.error_response
            if (
                (
                    course_auth_result.result.oseh_flags
                    & courses_auth.CourseAccessFlags.VIEW_METADATA
                )
                == 0
                or course_auth_result.result.claims is None
                or not isinstance(
                    course_auth_result.result.claims.get("exp"), (int, float)
                )
            ):
                return AUTHORIZATION_UNKNOWN_TOKEN

            args.filters.uid = FilterTextItemModel(
                operator=StandardTextOperator.EQUAL_CASE_SENSITIVE,
                value=course_auth_result.result.course_uid,
            )
            jwt_expires_at = int(course_auth_result.result.claims["exp"])
            jwt_no_entitlement_access_flags = course_auth_result.result.oseh_flags
            jwt_has_entitlement_access_flags = jwt_no_entitlement_access_flags

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
            jwt_expires_at=jwt_expires_at,
            jwt_has_entitlement_access_flags=jwt_has_entitlement_access_flags,
            jwt_no_entitlement_access_flags=jwt_no_entitlement_access_flags,
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
                jwt_expires_at=jwt_expires_at,
                jwt_has_entitlement_access_flags=jwt_has_entitlement_access_flags,
                jwt_no_entitlement_access_flags=jwt_no_entitlement_access_flags,
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
    category: Optional[Literal["list", "library"]],
    user_sub: str,
    jwt_expires_at: int,
    jwt_no_entitlement_access_flags: courses_auth.CourseAccessFlags,
    jwt_has_entitlement_access_flags: courses_auth.CourseAccessFlags,
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
    image_file_exports = Table("image_file_exports")
    intro_video_thumbnail_exports = image_file_exports.as_("ivte")
    first_journey_blurred_background_images = image_files.as_("fjbbi")
    course_journeys_inner = course_journeys.as_("cji")
    journeys_inner = Table("journeys").as_("ji")

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
            intro_video_thumbnail_exports.thumbhash,
            first_journey_blurred_background_images.uid,
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
        .left_outer_join(intro_video_thumbnail_exports)
        .on(
            (intro_video_thumbnail_exports.image_file_id == intro_video_thumbnails.id)
            & (intro_video_thumbnail_exports.width == 180)
            & (intro_video_thumbnail_exports.height == 368)
            & Not(
                ExistsCriterion(
                    Query.from_(image_file_exports)
                    .select(1)
                    .where(
                        (image_file_exports.image_file_id == intro_video_thumbnails.id)
                        & (image_file_exports.width == 180)
                        & (image_file_exports.height == 368)
                        & (image_file_exports.uid < intro_video_thumbnail_exports.uid)
                    )
                )
            )
        )
        .left_outer_join(first_journey_blurred_background_images)
        .on(
            first_journey_blurred_background_images.id
            == (
                Query.from_(course_journeys_inner)
                .select(journeys_inner.blurred_background_image_file_id)
                .join(journeys_inner)
                .on(journeys_inner.id == course_journeys_inner.journey_id)
                .where(course_journeys_inner.course_id == courses.id)
                .orderby(course_journeys_inner.priority)
                .limit(1)
            )
        )
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
        assert category is None, category

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
                itgs, row=ExternalCourseRow(*row), user_sub=None, skip_jwts=True
            )
        )

    if not items:
        return []

    relevant_entitlements = list(set(item.revenue_cat_entitlement for item in items))
    # PERF:
    #   due to how the cache is currently constructed its faster not to gather here;
    #   we should fix this in the users.lib.entitlements module
    #
    #   specifically, if we gather and the cache is empty we will stampede the requests
    #   instead of automatically delaying until the first result and reusing the result
    #   for the rest
    entitlements_result = [
        await user_entitlements.get_entitlement(itgs, user_sub=user_sub, identifier=ent)
        for ent in relevant_entitlements
    ]
    have_entitlements: Set[str] = set()
    for ent, result in zip(relevant_entitlements, entitlements_result):
        if result is not None and result.is_active:
            have_entitlements.add(ent)

    for item in items:
        item.has_entitlement = item.revenue_cat_entitlement in have_entitlements
        item.jwt = await courses_auth.create_jwt(
            itgs,
            item.uid,
            flags=(
                jwt_has_entitlement_access_flags
                if item.has_entitlement
                else jwt_no_entitlement_access_flags
            ),
            expires_at=jwt_expires_at,
        )

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
