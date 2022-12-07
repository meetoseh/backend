from pypika import Table, Query, Parameter
from pypika.queries import QueryBuilder
from pypika.terms import Term
from typing import Any, Dict, List, Literal, Optional, Tuple, Union
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE
from resources.filter import sort_criterion, flattened_filters
from resources.filter_item import FilterItem, FilterItemModel
from resources.sort import cleanup_sort, get_next_page_sort, reverse_sort
from resources.sort_item import SortItem, SortItemModel
from resources.filter_text_item import FilterTextItem, FilterTextItemModel
from itgs import Itgs
from resources.standard_text_operator import StandardTextOperator


class JourneySubcategory(BaseModel):
    uid: str = Field(description="The uid of the journey subcategory")
    internal_name: str = Field(
        description="The internal name of the journey subcategory"
    )
    external_name: str = Field(
        description="The external name of the journey subcategory"
    )


JOURNEY_SUBCATEGORY_SORT_OPTIONS = [
    SortItem[Literal["uid"], str],
    SortItem[Literal["internal_name"], str],
    SortItem[Literal["external_name"], str],
]
JourneySubcategorySortOption = Union[
    SortItemModel[Literal["uid"], str],
    SortItemModel[Literal["internal_name"], str],
    SortItemModel[Literal["external_name"], str],
]


class JourneySubcategoryFilter(BaseModel):
    uid: Optional[FilterTextItemModel] = Field(
        None, description="the uid of the journey subcategory"
    )
    internal_name: Optional[FilterTextItemModel] = Field(
        None, description="the internal name of the journey subcategory"
    )
    external_name: Optional[FilterTextItemModel] = Field(
        None, description="the external name of the journey subcategory"
    )


class ReadJourneySubcategoryRequest(BaseModel):
    filters: JourneySubcategoryFilter = Field(
        default_factory=JourneySubcategoryFilter, description="the filters to apply"
    )
    sort: Optional[List[JourneySubcategorySortOption]] = Field(
        None, description="the order to sort by"
    )
    limit: int = Field(
        100, description="the maximum number of results to return", ge=1, le=1000
    )


class ReadJourneySubcategoryResponse(BaseModel):
    items: List[JourneySubcategory] = Field(
        description="the items matching the request in the given sort"
    )
    next_page_sort: Optional[List[JourneySubcategorySortOption]] = Field(
        description="if there is a next or earlier page, the sort to use to get it"
    )


router = APIRouter()


@router.post(
    "/search",
    response_model=ReadJourneySubcategoryResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_journey_subcategories(
    args: ReadJourneySubcategoryRequest, authorization: Optional[str] = Header(None)
):
    """lists journey subcategories

    This requires standard authorization for an admin user.
    """
    sort = [srt.to_result() for srt in (args.sort or [])]
    sort = cleanup_sort(JOURNEY_SUBCATEGORY_SORT_OPTIONS, sort, ["uid"])
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response
        filters_to_apply = flattened_filters(
            dict(
                (k, v.to_result())
                for k, v in args.filters.__dict__.items()
                if v is not None
            )
        )
        items = await raw_read_journey_subcategories(
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
            rev_items = await raw_read_journey_subcategories(
                itgs, filters_to_apply, rev_sort, 1
            )
            if rev_items:
                first_item = item_pseudocolumns(items[0])

        if first_item is not None or last_item is not None:
            next_page_sort = get_next_page_sort(first_item, last_item, sort)

        return Response(
            content=ReadJourneySubcategoryResponse(
                items=items,
                next_page_sort=[s.to_model() for s in next_page_sort]
                if next_page_sort is not None
                else None,
            ).json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )


async def raw_read_journey_subcategories(
    itgs: Itgs,
    filters_to_apply: List[Tuple[str, Union[FilterItem, FilterTextItem]]],
    sort: List[SortItem],
    limit: int,
):
    """performs exactly the specified sort without pagination logic"""
    journey_subcategories = Table("journey_subcategories")

    query: QueryBuilder = Query.from_(journey_subcategories).select(
        journey_subcategories.uid,
        journey_subcategories.internal_name,
        journey_subcategories.external_name,
    )
    qargs = []

    def pseudocolumn(key: str) -> Term:
        if key in ("uid", "internal_name", "external_name"):
            return journey_subcategories.field(key)
        raise ValueError(f"unknown key: {key}")

    query = query.where(sort_criterion(sort, pseudocolumn, qargs))

    for srt in sort:
        query = query.orderby(pseudocolumn(srt.key), order=srt.order)

    query = query.limit(Parameter("?"))
    qargs.append(limit)

    conn = await itgs.conn()
    cursor = conn.cursor("none")
    response = await cursor.execute(query.get_sql(), qargs)
    items: List[JourneySubcategory] = []
    for row in response.results or []:
        items.append(
            JourneySubcategory(
                uid=row[0],
                internal_name=row[1],
                external_name=row[2],
            )
        )
    return items


def item_pseudocolumns(item: JourneySubcategory) -> dict:
    """returns the dictified item such that the keys in the return dict match
    the keys of the sort options"""
    return item.dict()
