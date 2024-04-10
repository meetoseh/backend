import time
from pypika import Table, Query, Parameter
from pypika.queries import QueryBuilder
from pypika.terms import Term, Function, ExistsCriterion, Not
from typing import Annotated, Any, Dict, List, Literal, Optional, Tuple, Union, cast
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from auth import auth_admin, auth_any
from journeys.models.series_flags import SeriesFlags
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse, ERROR_403_TYPE
from resources.bit_field_mutator import BitFieldMutator
from resources.filter import sort_criterion, flattened_filters
from resources.filter_bit_field_item import (
    BitFieldMutationModel,
    FilterBitFieldItemModel,
)
from resources.filter_item import FilterItemModel
from resources.filter_item_like import FilterItemLike
from resources.sort import cleanup_sort, get_next_page_sort, reverse_sort
from resources.sort_item import SortItem, SortItemModel
from resources.filter_text_item import FilterTextItemModel
from itgs import Itgs
from image_files.models import ImageFileRef
import image_files.auth as image_files_auth
from journeys.models.minimal_journey import MinimalJourney, MinimalJourneyInstructor
from journeys.models.minimal_course_journey import MinimalCourse, MinimalCourseJourney
from resources.standard_operator import StandardOperator
import courses.auth as courses_auth
from resources.standard_text_operator import StandardTextOperator


USER_COURSE_JOURNEY_SORT_OPTIONS = [
    SortItem[Literal["journey_uid"], str],
    SortItem[Literal["course_uid"], str],
    SortItem[Literal["association_uid"], str],
    SortItem[Literal["joined_course_at"], float],
    SortItem[Literal["priority"], int],
]
UserCourseJourneySortOption = Union[
    SortItemModel[Literal["journey_uid"], str],
    SortItemModel[Literal["course_uid"], str],
    SortItemModel[Literal["association_uid"], str],
    SortItemModel[Literal["joined_course_at"], float],
    SortItemModel[Literal["priority"], int],
]


class UserCourseJourneyFilter(BaseModel):
    journey_uid: Optional[FilterItemModel[str]] = Field(
        None, description="the uid of the journey"
    )
    journey_title: Optional[FilterTextItemModel] = Field(
        None, description="the title of the journey"
    )
    journey_instructor_name: Optional[FilterTextItemModel] = Field(
        None, description="the name of the instructor of the journey"
    )
    journey_last_taken_at: Optional[FilterItemModel[float]] = Field(
        None, description="the last time the journey was taken by the user"
    )
    journey_liked_at: Optional[FilterItemModel[float]] = Field(
        None, description="the last time the journey was liked by the user"
    )
    course_uid: Optional[FilterTextItemModel] = Field(
        None, description="the uid of the course"
    )
    course_flags: Optional[FilterBitFieldItemModel] = Field(
        None,
        description="the access flags for the course. this filter can only be set by admins",
    )
    association_uid: Optional[FilterItemModel[str]] = Field(
        None,
        description="the uid of the association between the course and the journey",
    )
    joined_course_at: Optional[FilterItemModel[float]] = Field(
        None, description="the time the user was added to the course"
    )
    priority: Optional[FilterItemModel[int]] = Field(
        None, description="the priority of the journey within the course"
    )


class ReadUserCourseJourneysRequest(BaseModel):
    filters: UserCourseJourneyFilter = Field(
        default_factory=lambda: UserCourseJourneyFilter.model_validate({}),
        description="the filters to apply",
    )
    sort: Optional[List[UserCourseJourneySortOption]] = Field(
        None, description="the sort order to apply"
    )
    limit: int = Field(
        15, description="the maximum number of results to return", ge=1, le=150
    )


class ReadUserCourseJourneysResponse(BaseModel):
    items: List[MinimalCourseJourney] = Field(
        description="the items matching the request in the given sort"
    )
    next_page_sort: Optional[List[UserCourseJourneySortOption]] = Field(
        None,
        description="if there is a next/previous page, the sort order to use to get the next page",
    )


router = APIRouter()


@router.post(
    "/search_course_journeys",
    response_model=ReadUserCourseJourneysResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_user_course_journeys(
    args: ReadUserCourseJourneysRequest,
    admin: Optional[str] = None,
    course_jwt: Optional[str] = None,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Lists out journeys within courses.

    If the `admin` query parameter not set to `1`, the filters must show
    that the user has access to the corresponding courses, or `course_jwt`
    can be set to a JWT for a course, and the `course_uid` filter will be
    overridden to match the course in the JWT.

    The user can either show access via the course flags filter being unset
    (which will be treated as visible in owned and joined), or by explicitly
    setting filters to one of the following:

    ### visible in owned and attached

    ```json
    {
        "course_flags": {
            "mutation": {"operator": "and", "value": 16},
            "comparison": {"operator": "neq", "value": 0}
        },
        "joined_course_at": {"operator": "neq", "value": null}
    }
    ```

    ### visible in series tab

    ```json
    {
        "course_flags": {
            "mutation": {"operator": "and", "value": 64},
            "comparison": {"operator": "neq", "value": 0}
        }
    }
    ```

    Requires standard authorization if `admin` is not set to `1` and admin
    authorization otherwise. If `course_jwt` is set, must be a valid JWT
    for a course with the VIEW_METADATA flag set.

    To prevent using this to extend the duration of JWTs or expand their scope,
    if a `course_jwt` is used for authorization, the returned jwts will have the
    same expiration and flags as the input jwt. Otherwise, they will have around
    a 30m expiration and the VIEW_METADATA/LIKE flag.
    """
    using_admin_perms = admin == "1"
    using_course_jwt = course_jwt is not None

    sort = [srt.to_result() for srt in (args.sort or [])]
    sort = cleanup_sort(USER_COURSE_JOURNEY_SORT_OPTIONS, sort, ["association_uid"])
    async with Itgs() as itgs:
        auth_result = (
            await auth_any(itgs, authorization)
            if not using_admin_perms
            else await auth_admin(itgs, authorization)
        )
        if auth_result.result is None:
            return auth_result.error_response

        course_auth_result = None
        jwts_expire_at = int(time.time() + 1800)
        course_access_flags = (
            courses_auth.CourseAccessFlags.VIEW_METADATA
            | courses_auth.CourseAccessFlags.LIKE
        )
        if using_course_jwt:
            course_auth_result = await courses_auth.auth_any(
                itgs, f"bearer {course_jwt}"
            )
            if course_auth_result.result is None:
                return course_auth_result.error_response

            if course_auth_result.result.claims is None:
                raise ValueError("claims should not be None")

            if (
                course_auth_result.result.oseh_flags
                & courses_auth.CourseAccessFlags.VIEW_METADATA
                == 0
            ):
                return Response(
                    content=StandardErrorResponse[ERROR_403_TYPE](
                        type="invalid",
                        message="course jwt does not have view metadata flag",
                    ).model_dump_json(),
                    status_code=403,
                    headers={"Content-Type": "application/json; charset=utf-8"},
                )

            input_expires_at = course_auth_result.result.claims["exp"]
            if not isinstance(input_expires_at, (int, float)):
                raise ValueError("exp should be an int or float")

            jwts_expire_at = min(jwts_expire_at, int(input_expires_at))
            course_access_flags = course_auth_result.result.oseh_flags

            args.filters.course_uid = FilterTextItemModel(
                operator=StandardTextOperator.EQUAL_CASE_SENSITIVE,
                value=course_auth_result.result.course_uid,
            )

        if not using_admin_perms and not using_course_jwt:
            if (
                args.filters.course_flags is None
                and args.filters.joined_course_at is None
            ):
                args.filters.course_flags = FilterBitFieldItemModel(
                    mutation=BitFieldMutationModel(
                        operator=BitFieldMutator.AND,
                        value=SeriesFlags.SERIES_VISIBLE_IN_OWNED,
                    ),
                    comparison=FilterItemModel[int](
                        operator=StandardOperator.NOT_EQUAL, value=0
                    ),
                )
                args.filters.joined_course_at = FilterItemModel[float](
                    operator=StandardOperator.NOT_EQUAL, value=None
                )
            elif args.filters.course_flags is None:
                joined_course_filter = cast(
                    FilterItemModel[float], args.filters.joined_course_at
                ).to_result()
                if (
                    joined_course_filter.operator != StandardOperator.NOT_EQUAL
                    or joined_course_filter.value is not None
                ):
                    return Response(
                        content=StandardErrorResponse[ERROR_403_TYPE](
                            type="invalid",
                            message=(
                                "if course_flags filter is unset, joined_course_at must be unset or set to neq null"
                            ),
                        ).model_dump_json(),
                        status_code=403,
                        headers={"Content-Type": "application/json; charset=utf-8"},
                    )
                args.filters.course_flags = FilterBitFieldItemModel(
                    mutation=BitFieldMutationModel(
                        operator=BitFieldMutator.AND,
                        value=SeriesFlags.SERIES_VISIBLE_IN_OWNED,
                    ),
                    comparison=FilterItemModel[int](
                        operator=StandardOperator.NOT_EQUAL, value=0
                    ),
                )
            else:
                # course_flags is set, joined_course_at might be set
                course_flags_filter = args.filters.course_flags.to_result()
                if (
                    course_flags_filter.mutation is None
                    or course_flags_filter.mutation.operator != BitFieldMutator.AND
                    or course_flags_filter.comparison.operator
                    != StandardOperator.NOT_EQUAL
                    or course_flags_filter.comparison.value != 0
                ):
                    return Response(
                        content=StandardErrorResponse[ERROR_403_TYPE](
                            type="invalid",
                            message=(
                                "if course_flags filter is set, it must be set in the form (v AND flags) != 0"
                            ),
                        ).model_dump_json(),
                        status_code=403,
                        headers={"Content-Type": "application/json; charset=utf-8"},
                    )

                if course_flags_filter.mutation.value == int(
                    SeriesFlags.SERIES_IN_SERIES_TAB
                ):
                    # acceptable
                    ...
                elif course_flags_filter.mutation.value == int(
                    SeriesFlags.SERIES_VISIBLE_IN_OWNED
                ):
                    # for access, they need to have joined the course
                    if args.filters.joined_course_at is None:
                        args.filters.joined_course_at = FilterItemModel[float](
                            operator=StandardOperator.NOT_EQUAL, value=None
                        )
                    else:
                        joined_course_filter = cast(
                            FilterItemModel[float], args.filters.joined_course_at
                        ).to_result()
                        if (
                            joined_course_filter.operator != StandardOperator.NOT_EQUAL
                            or joined_course_filter.value is not None
                        ):
                            return Response(
                                content=StandardErrorResponse[ERROR_403_TYPE](
                                    type="invalid",
                                    message=(
                                        "if course_flags filter is set to visible in owned, joined_course_at must be unset or set to neq null"
                                    ),
                                ).model_dump_json(),
                                status_code=403,
                                headers={
                                    "Content-Type": "application/json; charset=utf-8"
                                },
                            )
                else:
                    return Response(
                        content=StandardErrorResponse[ERROR_403_TYPE](
                            type="invalid",
                            message=(
                                "course_flags filter is set to an invalid value for non-admin users"
                            ),
                        ).model_dump_json(),
                        status_code=403,
                        headers={"Content-Type": "application/json; charset=utf-8"},
                    )

        filters_to_apply = flattened_filters(
            dict(
                (k, cast(FilterItemLike, v.to_result()))
                for k, v in args.filters.__dict__.items()
                if v is not None
            )
        )
        items = await raw_read_user_course_journeys(
            itgs,
            filters_to_apply,
            sort,
            args.limit + 1,
            user_sub=auth_result.result.sub,
            jwts_expire_at=jwts_expire_at,
            course_access_flags=course_access_flags,
        )
        next_page_sort: Optional[List[SortItem]] = None
        last_item: Optional[Dict[str, Any]] = None
        if len(items) > args.limit:
            items = items[: args.limit]
            last_item = item_pseudocolumns(items[-1])
        first_item: Optional[Dict[str, Any]] = None
        if items and any(s.after is not None for s in sort):
            rev_sort = reverse_sort(sort, "make_exclusive")
            rev_items = await raw_read_user_course_journeys(
                itgs,
                filters_to_apply,
                rev_sort,
                1,
                user_sub=auth_result.result.sub,
                jwts_expire_at=jwts_expire_at,
                course_access_flags=course_access_flags,
            )
            if rev_items:
                first_item = item_pseudocolumns(items[0])

        if first_item is not None or last_item is not None:
            next_page_sort = get_next_page_sort(first_item, last_item, sort)

        return Response(
            content=ReadUserCourseJourneysResponse(
                items=items,
                next_page_sort=(
                    [s.to_model() for s in next_page_sort]
                    if next_page_sort is not None
                    else None
                ),
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )


async def raw_read_user_course_journeys(
    itgs: Itgs,
    filters_to_apply: List[Tuple[str, FilterItemLike]],
    sort: List[SortItem],
    limit: int,
    *,
    user_sub: str,
    jwts_expire_at: int,
    course_access_flags: courses_auth.CourseAccessFlags,
):
    """performs exactly the specified sort without pagination logic"""
    last_taken_at = Table("last_taken_at")

    course_journeys = Table("course_journeys")
    course_users = Table("course_users")
    courses = Table("courses")
    user_journeys = Table("user_journeys")
    users = Table("users")
    journeys = Table("journeys")
    image_files = Table("image_files")
    _instructors = Table("instructors")
    journey_instructors = _instructors.as_("journey_instructors")
    journey_instructor_pictures = image_files.as_("instructor_pictures")
    journey_darkened_background_images = image_files.as_("jdbi")
    user_likes = Table("user_likes")
    content_files = Table("content_files")
    journey_audio_contents = content_files.as_("journey_audio_contents")
    user_course_likes = Table("user_course_likes")

    course_journeys_inner = course_journeys.as_("cji")

    query: QueryBuilder = (
        Query.with_(
            Query.from_(user_journeys)
            .join(users)
            .on(users.id == user_journeys.user_id)
            .select(
                user_journeys.journey_id.as_("journey_id"),
                Function("MAX", user_journeys.created_at).as_("last_taken_at"),
            )
            .where(users.sub == Parameter("?"))
            .groupby(user_journeys.journey_id),
            last_taken_at.get_table_name(),
        )
        .from_(course_journeys)
        .select(
            course_journeys.uid,
            courses.uid,
            courses.title,
            user_course_likes.created_at,
            journeys.uid,
            journeys.title,
            journeys.description,
            journey_darkened_background_images.uid,
            journey_audio_contents.duration_seconds,
            journey_instructors.name,
            journey_instructor_pictures.uid,
            last_taken_at.last_taken_at,
            user_likes.created_at,
            course_journeys.priority,
            course_users.created_at,
            # is_next
            (
                # they are added to the journey
                course_users.id.isnotnull()
                # It's after the course_user's last_priority
                & (
                    course_users.last_priority.isnull()
                    | (course_journeys.priority > course_users.last_priority)
                )
                # AND there is no course journey with a lower priority whose
                # priority is greater than the course_user's last_priority
                & Not(
                    ExistsCriterion(
                        Query.from_(course_journeys_inner)
                        .select(1)
                        .where(
                            course_journeys_inner.course_id
                            == course_journeys.course_id,
                        )
                        .where(
                            course_journeys_inner.priority < course_journeys.priority,
                        )
                        .where(
                            (
                                course_users.last_priority.isnull()
                                | (
                                    course_journeys_inner.priority
                                    > course_users.last_priority
                                )
                            )
                        )
                    )
                )
            ).as_("is_next"),
        )
        .join(courses)
        .on(courses.id == course_journeys.course_id)
        .join(journeys)
        .on(journeys.id == course_journeys.journey_id)
        .join(users)
        .on(users.sub == Parameter("?"))
        .join(journey_instructors)
        .on(journey_instructors.id == journeys.instructor_id)
        .join(journey_darkened_background_images)
        .on(
            journeys.darkened_background_image_file_id
            == journey_darkened_background_images.id
        )
        .join(journey_audio_contents)
        .on(journey_audio_contents.id == journeys.audio_content_file_id)
        .left_outer_join(course_users)
        .on((course_users.course_id == courses.id) & (course_users.user_id == users.id))
        .left_outer_join(last_taken_at)
        .on(last_taken_at.journey_id == journeys.id)
        .left_outer_join(journey_instructor_pictures)
        .on(journey_instructor_pictures.id == journey_instructors.picture_image_file_id)
        .left_outer_join(user_likes)
        .on((user_likes.user_id == users.id) & (user_likes.journey_id == journeys.id))
        .left_outer_join(user_course_likes)
        .on(
            (user_course_likes.user_id == users.id)
            & (user_course_likes.course_id == courses.id)
        )
        .where(journeys.deleted_at.isnull())
    )
    qargs: List[Any] = [user_sub, user_sub]

    def pseudocolumn(key: str) -> Term:
        if key == "journey_uid":
            return journeys.uid
        elif key == "journey_title":
            return journeys.title
        elif key == "journey_instructor_name":
            return journey_instructors.name
        elif key == "journey_last_taken_at":
            return last_taken_at.last_taken_at
        elif key == "journey_liked_at":
            return user_likes.created_at
        elif key == "course_uid":
            return courses.uid
        elif key == "association_uid":
            return course_journeys.uid
        elif key == "joined_course_at":
            return course_users.created_at
        elif key == "priority":
            return course_journeys.priority
        elif key == "course_flags":
            return courses.flags
        raise ValueError(f"unknown {key=}")

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
    items: List[MinimalCourseJourney] = []
    for row in response.results or []:
        items.append(
            MinimalCourseJourney(
                association_uid=row[0],
                course=MinimalCourse(
                    uid=row[1],
                    title=row[2],
                    liked_at=row[3],
                    jwt=await courses_auth.create_jwt(
                        itgs,
                        row[1],
                        flags=course_access_flags,
                        expires_at=jwts_expire_at,
                    ),
                ),
                journey=MinimalJourney(
                    uid=row[4],
                    title=row[5],
                    description=row[6],
                    darkened_background=ImageFileRef(
                        uid=row[7],
                        jwt=await image_files_auth.create_jwt(
                            itgs, image_file_uid=row[7]
                        ),
                    ),
                    duration_seconds=row[8],
                    instructor=MinimalJourneyInstructor(
                        name=row[9],
                        image=(
                            None
                            if row[10] is None
                            else ImageFileRef(
                                uid=row[10],
                                jwt=await image_files_auth.create_jwt(
                                    itgs, image_file_uid=row[10]
                                ),
                            )
                        ),
                    ),
                    last_taken_at=row[11],
                    liked_at=row[12],
                ),
                priority=row[13],
                joined_course_at=row[14],
                is_next=bool(row[15]),
            )
        )
    return items


def item_pseudocolumns(item: MinimalCourseJourney) -> dict:
    """returns the dictified item such that the keys in the return dict match
    the keys of the sort options"""
    return {
        "journey_uid": item.journey.uid,
        "course_uid": item.course.uid,
        "association_uid": item.association_uid,
        "joined_course_at": item.joined_course_at,
        "priority": item.priority,
    }
