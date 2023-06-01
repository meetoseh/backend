import json
from pypika import Table, Query, Parameter
from pypika.queries import QueryBuilder
from pypika.terms import Term, Function
from typing import Any, Dict, List, Literal, Optional, Tuple, Union
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from auth import auth_any
from models import STANDARD_ERRORS_BY_CODE
from resources.filter import sort_criterion, flattened_filters
from resources.filter_item import FilterItem, FilterItemModel
from resources.sort import cleanup_sort, get_next_page_sort, reverse_sort
from resources.sort_item import SortItem, SortItemModel
from resources.filter_text_item import FilterTextItem, FilterTextItemModel
from itgs import Itgs
from image_files.models import ImageFileRef
import image_files.auth as image_files_auth
from journeys.models.minimal_journey import MinimalJourney, MinimalJourneyInstructor


USER_HISTORY_SORT_OPTIONS = [
    SortItem[Literal["uid"], str],
    SortItem[Literal["last_taken_at"], float],
    SortItem[Literal["liked_at"], Optional[float]],
]
UserHistorySortOption = Union[
    SortItemModel[Literal["uid"], str],
    SortItemModel[Literal["last_taken_at"], float],
    SortItemModel[Literal["liked_at"], Optional[float]],
]


class UserHistoryFilter(BaseModel):
    uid: Optional[FilterTextItemModel] = Field(
        None, description="the uid of the journey"
    )
    title: Optional[FilterTextItemModel] = Field(
        None, description="the title of the journey"
    )
    instructor_name: Optional[FilterTextItemModel] = Field(
        None, description="the name of the instructor"
    )
    last_taken_at: Optional[FilterItemModel[float]] = Field(
        None, description="the last time the journey was taken by the user"
    )
    liked_at: Optional[FilterItemModel[float]] = Field(
        None, description="the last time the journey was liked by the user"
    )


class ReadUserHistoryRequest(BaseModel):
    filters: UserHistoryFilter = Field(
        default_factory=UserHistoryFilter, description="the filters to apply"
    )
    sort: Optional[List[UserHistorySortOption]] = Field(
        None, description="the sort order to apply"
    )
    limit: int = Field(
        15, description="the maximum number of journeys to return", ge=1, le=150
    )


class ReadUserHistoryResponse(BaseModel):
    items: List[MinimalJourney] = Field(
        description="the items matching the request in the given sort"
    )
    next_page_sort: Optional[List[UserHistorySortOption]] = Field(
        None,
        description="if there is a next/previous page, the sort order to use to get the next page",
    )


router = APIRouter()


@router.post(
    "/search_history",
    response_model=ReadUserHistoryResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_user_history(
    args: ReadUserHistoryRequest, authorization: Optional[str] = Header(None)
):
    """Lists out journeys that the user has taken. The result items only contain
    the minimal information required to display these journeys in a listing; to
    start one of these journeys, use `start_journey_from_history`.

    Requires standard authorization.
    """
    sort = [srt.to_result() for srt in (args.sort or [])]
    sort = cleanup_sort(USER_HISTORY_SORT_OPTIONS, sort, ["uid"])
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response
        filters_to_apply = flattened_filters(
            dict(
                (k, v.to_result())
                for k, v in args.filters.__dict__.items()
                if v is not None
            )
        )
        items = await raw_read_user_history(
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
            rev_items = await raw_read_user_history(
                itgs, filters_to_apply, rev_sort, 1, user_sub=auth_result.result.sub
            )
            if rev_items:
                first_item = item_pseudocolumns(items[0])

        if first_item is not None or last_item is not None:
            next_page_sort = get_next_page_sort(first_item, last_item, sort)

        return Response(
            content=ReadUserHistoryResponse(
                items=items,
                next_page_sort=[s.to_model() for s in next_page_sort]
                if next_page_sort is not None
                else None,
            ).json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )


async def raw_read_user_history(
    itgs: Itgs,
    filters_to_apply: List[Tuple[str, Union[FilterItem, FilterTextItem]]],
    sort: List[SortItem],
    limit: int,
    *,
    user_sub: str,
):
    """performs exactly the specified sort without pagination logic"""
    last_taken_at = Table("last_taken_at")

    user_journeys = Table("user_journeys")
    users = Table("users")
    journeys = Table("journeys")
    image_files = Table("image_files")
    instructors = Table("instructors")
    instructor_pictures = image_files.as_("instructor_pictures")
    user_likes = Table("user_likes")

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
        .from_(journeys)
        .select(
            journeys.uid,
            journeys.title,
            instructors.name,
            instructor_pictures.uid,
            last_taken_at.last_taken_at,
            user_likes.created_at,
        )
        .join(users)
        .on(users.sub == Parameter("?"))
        .join(instructors)
        .on(instructors.id == journeys.instructor_id)
        .join(last_taken_at)
        .on(last_taken_at.journey_id == journeys.id)
        .left_outer_join(instructor_pictures)
        .on(instructor_pictures.id == instructors.picture_image_file_id)
        .left_outer_join(user_likes)
        .on(
            (user_likes.user_id == user_journeys.user_id)
            & (user_likes.journey_id == journeys.id)
        )
        .where(journeys.deleted_at.isnull())
    )
    qargs = [user_sub, user_sub]

    def pseudocolumn(key: str) -> Term:
        if key in ("uid", "title"):
            return journeys.field(key)
        elif key == "instructor_name":
            return instructors.field("name")
        elif key == "last_taken_at":
            return last_taken_at.field("last_taken_at")
        elif key == "liked_at":
            return user_likes.field("created_at")
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
    items: List[MinimalJourney] = []
    for row in response.results or []:
        items.append(
            MinimalJourney(
                uid=row[0],
                title=row[1],
                instructor=MinimalJourneyInstructor(
                    name=row[2],
                    image=(
                        None
                        if row[3] is None
                        else ImageFileRef(
                            uid=row[3],
                            jwt=await image_files_auth.create_jwt(
                                itgs, image_file_uid=row[3]
                            ),
                        )
                    ),
                ),
                last_taken_at=row[4],
                liked_at=row[5],
            )
        )
    return items


def item_pseudocolumns(item: MinimalJourney) -> dict:
    """returns the dictified item such that the keys in the return dict match
    the keys of the sort options"""
    return {
        "uid": item.uid,
        "last_taken_at": item.last_taken_at,
        "liked_at": item.liked_at,
    }
