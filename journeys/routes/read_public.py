import math
from pypika import Table, Query, Parameter, Not
from pypika.queries import QueryBuilder
from pypika.terms import Term, ExistsCriterion, BitwiseAndCriterion
from typing import Any, Dict, List, Literal, Optional, Tuple, Union, cast
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from auth import auth_any
from db.utils import ParenthisizeCriterion
from journeys.models.series_flags import SeriesFlags
from models import STANDARD_ERRORS_BY_CODE
from resources.filter import sort_criterion, flattened_filters
from resources.filter_in_item import FilterInItem
from resources.filter_item import FilterItemModel
from resources.filter_item_like import FilterItemLike
from resources.sort import cleanup_sort, get_next_page_sort, reverse_sort
from resources.sort_item import SortItem, SortItemModel
from resources.filter_text_item import FilterTextItemModel
from itgs import Itgs


class SearchPublicJourneyInstructor(BaseModel):
    uid: str = Field(
        description="The primary stable external identifier for this instructor"
    )
    name: str = Field(description="The full name of the instructor")


class SearchPublicJourney(BaseModel):
    uid: str = Field(description="The primary stable unique identifier of the journey")
    title: str = Field(description="The title for the journey")
    duration_seconds: int = Field(
        description="The duration of the class audio in seconds, rounded up"
    )
    instructor: SearchPublicJourneyInstructor = Field(
        description="The instructor for the journey"
    )
    last_taken_at: Optional[float] = Field(
        None, description="the last time the journey was taken by the user"
    )
    liked_at: Optional[float] = Field(
        None, description="the last time the journey was liked by the user"
    )
    requires_pro: bool = Field(
        description="Whether the journey requires a pro subscription or not"
    )


SEARCH_PUBLIC_JOURNEY_SORT_OPTIONS = [
    SortItem[Literal["uid"], str],
    SortItem[Literal["title"], str],
    SortItem[Literal["duration_seconds"], int],
    SortItem[Literal["instructor_uid"], str],
    SortItem[Literal["instructor_name"], str],
    SortItem[Literal["last_taken_at"], float],
    SortItem[Literal["liked_at"], float],
]
SearchPublicJourneySortOption = Union[
    SortItemModel[Literal["uid"], str],
    SortItemModel[Literal["title"], str],
    SortItemModel[Literal["duration_seconds"], int],
    SortItemModel[Literal["instructor_uid"], str],
    SortItemModel[Literal["instructor_name"], str],
    SortItemModel[Literal["last_taken_at"], float],
    SortItemModel[Literal["liked_at"], float],
]


class SearchPublicJourneyFilter(BaseModel):
    uid: Optional[FilterTextItemModel] = Field(
        None, description="the uid of the journey"
    )
    title: Optional[FilterTextItemModel] = Field(
        None, description="the title of the journey"
    )
    duration_seconds: Optional[FilterItemModel[int]] = Field(
        None, description="the duration of the journey in seconds"
    )
    instructor_uid: Optional[FilterTextItemModel] = Field(
        None, description="the uid of the instructor of the journey"
    )
    instructor_uid_in: Optional[List[str]] = Field(
        None,
        description="if not None, matches iff the instructor uid is in this list",
    )
    instructor_name: Optional[FilterTextItemModel] = Field(
        None, description="the name of the instructor of the journey"
    )
    last_taken_at: Optional[FilterItemModel[float]] = Field(
        None, description="the last time the journey was taken by the user"
    )
    liked_at: Optional[FilterItemModel[float]] = Field(
        None, description="the last time the journey was liked by the user"
    )
    requires_pro: Optional[FilterItemModel[bool]] = Field(
        None, description="whether the journey requires a pro subscription or not"
    )


class ReadSearchPublicJourneyRequest(BaseModel):
    filters: SearchPublicJourneyFilter = Field(
        default_factory=lambda: SearchPublicJourneyFilter.model_validate({}),
        description="the filters to apply",
    )
    sort: Optional[List[SearchPublicJourneySortOption]] = Field(
        None, description="the order to sort by"
    )
    limit: int = Field(
        25, description="the maximum number of journeys to return", ge=1, le=250
    )


class ReadSearchPublicJourneyResponse(BaseModel):
    items: List[SearchPublicJourney] = Field(
        description="the items matching the filters in the given sort"
    )
    next_page_sort: Optional[List[SearchPublicJourneySortOption]] = Field(
        description=(
            "if there is a next page or an earlier page, provides the necessary "
            "sort criteria to get it"
        )
    )


router = APIRouter()


@router.post(
    "/search_public",
    response_model=ReadSearchPublicJourneyResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_public_journeys(
    args: ReadSearchPublicJourneyRequest, authorization: Optional[str] = Header(None)
):
    """Lists out journeys that go in the general Classes tab (i.e., not specific to the
    user), as they relate to the user.

    This requires standard authentication with an admin account.
    """
    sort = [srt.to_result() for srt in (args.sort or [])]
    sort = cleanup_sort(SEARCH_PUBLIC_JOURNEY_SORT_OPTIONS, sort, ["uid"])
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response
        filters_to_apply = flattened_filters(
            dict(
                (k, cast(FilterItemLike, v.to_result()))
                for k, v in args.filters.__dict__.items()
                if v is not None and k != "instructor_uid_in"
            )
        )
        if args.filters.instructor_uid_in is not None:
            filters_to_apply.append(
                (
                    "instructor_uid",
                    cast(
                        FilterItemLike,
                        FilterInItem[str](args.filters.instructor_uid_in),
                    ),
                )
            )

        items = await raw_read_search_public_journeys(
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
            rev_items = await raw_read_search_public_journeys(
                itgs, filters_to_apply, rev_sort, 1, user_sub=auth_result.result.sub
            )
            if rev_items:
                first_item = item_pseudocolumns(items[0])

        if first_item is not None or last_item is not None:
            next_page_sort = get_next_page_sort(first_item, last_item, sort)

        return Response(
            content=ReadSearchPublicJourneyResponse(
                items=items,
                next_page_sort=(
                    [s.to_model() for s in next_page_sort]
                    if next_page_sort is not None
                    else None
                ),
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )


async def raw_read_search_public_journeys(
    itgs: Itgs,
    filters_to_apply: List[Tuple[str, FilterItemLike]],
    sort: List[SortItem],
    limit: int,
    /,
    *,
    user_sub: str,
):
    """performs exactly the specified sort without pagination logic"""
    journeys = Table("journeys")
    instructors = Table("instructors")
    users = Table("users")
    user_likes = Table("user_likes")
    content_files = Table("content_files")

    # only in inner queries
    courses = Table("courses")
    course_journeys = Table("course_journeys")

    # ctes
    last_taken_ats = Table("last_taken_ats")
    premium_journeys = Table("premium_journeys")

    users_inner = users.as_("u")

    last_taken_ats_cte = """
last_taken_ats(journey_id, created_at) AS (
    SELECT journey_id, MAX(created_at)
    FROM user_journeys
    WHERE
        user_id = (
            SELECT users.id FROM users WHERE users.sub = ?
        )
    GROUP BY journey_id
)
    """
    last_taken_ats_cte_qargs: list = [user_sub]

    premium_journeys_cte = f"""
premium_journeys(journey_id) AS (
    SELECT course_journeys.journey_id
    FROM course_journeys, courses
    WHERE
        course_journeys.course_id = courses.id
        AND (courses.flags & {int(SeriesFlags.JOURNEYS_IN_SERIES_ARE_PREMIUM)}) != 0
)
"""
    premium_journeys_qargs: list = []

    query: QueryBuilder = (
        Query.from_(journeys)
        .select(
            journeys.uid,
            journeys.title,
            content_files.duration_seconds,
            instructors.uid,
            instructors.name,
            ParenthisizeCriterion(
                Query.from_(last_taken_ats)
                .select(last_taken_ats.created_at)
                .where(journeys.id == last_taken_ats.journey_id),
                "last_taken_at",
            ),
            user_likes.created_at,
            ParenthisizeCriterion(
                ExistsCriterion(
                    Query.from_(
                        premium_journeys,
                    )
                    .select(1)
                    .where(journeys.id == premium_journeys.journey_id)
                ),
                "is_premium",
            ),
        )
        .join(content_files)
        .on(content_files.id == journeys.audio_content_file_id)
        .join(instructors)
        .on(instructors.id == journeys.instructor_id)
        .left_join(user_likes)
        .on(
            # Doing this here ensures sqlite only evaluates it once during the
            # setup phase
            (
                user_likes.user_id
                == ParenthisizeCriterion(
                    Query.from_(users_inner)
                    .select(users_inner.id)
                    .where(users_inner.sub == Parameter("?"))
                )
            )
            & (user_likes.journey_id == journeys.id)
        )
        .where(journeys.deleted_at.isnull())
        .where(journeys.special_category.isnull())
        .where(
            Not(
                ExistsCriterion(
                    Query.from_(courses)
                    .select(1)
                    .join(course_journeys)
                    .on(course_journeys.course_id == courses.id)
                    .where(course_journeys.journey_id == journeys.id)
                    .where(
                        BitwiseAndCriterion(
                            courses.flags,
                            Term.wrap_constant(
                                int(SeriesFlags.JOURNEYS_IN_SERIES_IN_LIBRARY)
                            ),
                        )
                        == 0
                    )
                )
            )
        )
    )
    qargs: list = [user_sub]

    def pseudocolumn(key: str) -> Term:
        if key in ("uid", "title"):
            return journeys.field(key)
        if key == "duration_seconds":
            return content_files.field(key)
        if key == "instructor_uid":
            return instructors.field("uid")
        if key == "instructor_name":
            return instructors.field("name")
        if key == "last_taken_at":
            return ParenthisizeCriterion(
                Query.from_(last_taken_ats)
                .select(last_taken_ats.created_at)
                .where(journeys.id == last_taken_ats.journey_id)
            )
        if key == "liked_at":
            return user_likes.created_at
        if key == "requires_pro":
            return ParenthisizeCriterion(
                ExistsCriterion(
                    Query.from_(premium_journeys)
                    .select(1)
                    .where(journeys.id == premium_journeys.journey_id)
                )
            )
        raise ValueError(f"unknown key: {key}")

    for key, filter in filters_to_apply:
        query = query.where(filter.applied_to(pseudocolumn(key), qargs))

    query = query.where(sort_criterion(sort, pseudocolumn, qargs))

    for srt in sort:
        query = query.orderby(pseudocolumn(srt.key), order=srt.order)

    query = query.limit(Parameter("?"))
    qargs.append(limit)

    sql = (
        "WITH "
        + last_taken_ats_cte
        + ", "
        + premium_journeys_cte
        + " "
        + query.get_sql()
    )
    full_qargs = last_taken_ats_cte_qargs + premium_journeys_qargs + qargs

    conn = await itgs.conn()
    cursor = conn.cursor("none")
    response = await cursor.execute(sql, full_qargs)
    items: List[SearchPublicJourney] = []
    for row in response.results or []:
        items.append(
            SearchPublicJourney(
                uid=row[0],
                title=row[1],
                duration_seconds=math.ceil(row[2]),
                instructor=SearchPublicJourneyInstructor(uid=row[3], name=row[4]),
                last_taken_at=row[5],
                liked_at=row[6],
                requires_pro=bool(row[7]),
            )
        )
    return items


def item_pseudocolumns(item: SearchPublicJourney) -> dict:
    """returns the dictified item such that the keys in the return dict match
    the keys of the sort options"""
    return {
        "uid": item.uid,
        "title": item.title,
        "duration_seconds": item.duration_seconds,
        "instructor_uid": item.instructor.uid,
        "instructor_name": item.instructor.name,
        "last_taken_at": item.last_taken_at,
        "liked_at": item.liked_at,
        "requires_pro": item.requires_pro,
    }
