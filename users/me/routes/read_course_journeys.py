from pypika import Table, Query, Parameter
from pypika.queries import QueryBuilder
from pypika.terms import Term, Function, ExistsCriterion, Not
from typing import Any, Dict, List, Literal, Optional, Tuple, Union, cast
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from auth import auth_any
from journeys.models.series_flags import SeriesFlags
from models import STANDARD_ERRORS_BY_CODE
from resources.filter import sort_criterion, flattened_filters
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
    course_uid: Optional[FilterItemModel[str]] = Field(
        None, description="the uid of the course"
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
    args: ReadUserCourseJourneysRequest, authorization: Optional[str] = Header(None)
):
    """Lists out journeys within courses that the user has started, regardless of
    if they've finished them or not. To start one of these journeys, use
    `start_journey_in_course` (under courses)

    Requires standard authorization.
    """
    sort = [srt.to_result() for srt in (args.sort or [])]
    sort = cleanup_sort(USER_COURSE_JOURNEY_SORT_OPTIONS, sort, ["association_uid"])
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
        items = await raw_read_user_course_journeys(
            itgs,
            filters_to_apply,
            sort,
            args.limit + 1,
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
            rev_items = await raw_read_user_course_journeys(
                itgs, filters_to_apply, rev_sort, 1, user_sub=auth_result.result.sub
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
    instructors = Table("instructors")
    instructor_pictures = image_files.as_("instructor_pictures")
    user_likes = Table("user_likes")

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
            journeys.uid,
            journeys.title,
            instructors.name,
            instructor_pictures.uid,
            last_taken_at.last_taken_at,
            user_likes.created_at,
            course_journeys.priority,
            course_users.created_at,
            # is_next
            (
                # It's after the course_user's last_priority
                (
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
        .join(course_users)
        .on((course_users.course_id == courses.id) & (course_users.user_id == users.id))
        .join(instructors)
        .on(instructors.id == journeys.instructor_id)
        .left_outer_join(last_taken_at)
        .on(last_taken_at.journey_id == journeys.id)
        .left_outer_join(instructor_pictures)
        .on(instructor_pictures.id == instructors.picture_image_file_id)
        .left_outer_join(user_likes)
        .on((user_likes.user_id == users.id) & (user_likes.journey_id == journeys.id))
        .where(journeys.deleted_at.isnull())
        .where(
            (courses.flags & Parameter('?')) != 0
        )
    )
    qargs: List[Any] = [user_sub, user_sub, int(SeriesFlags.SERIES_VISIBLE_IN_OWNED)]

    def pseudocolumn(key: str) -> Term:
        if key == "journey_uid":
            return journeys.uid
        elif key == "journey_title":
            return journeys.title
        elif key == "journey_instructor_name":
            return instructors.name
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
                ),
                journey=MinimalJourney(
                    uid=row[3],
                    title=row[4],
                    instructor=MinimalJourneyInstructor(
                        name=row[5],
                        image=(
                            None
                            if row[6] is None
                            else ImageFileRef(
                                uid=row[6],
                                jwt=await image_files_auth.create_jwt(
                                    itgs, image_file_uid=row[6]
                                ),
                            )
                        ),
                    ),
                    last_taken_at=row[7],
                    liked_at=row[8],
                ),
                priority=row[9],
                joined_course_at=row[10],
                is_next=bool(row[11]),
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
