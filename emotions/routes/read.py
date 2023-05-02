from pypika import Table, Query, Parameter
from pypika.queries import QueryBuilder
from pypika.terms import Term, ExistsCriterion
from typing import Any, Dict, List, Literal, Optional, Tuple, Union
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE
from resources.filter import sort_criterion, flattened_filters
from resources.filter_item import FilterItem
from resources.sort import cleanup_sort, get_next_page_sort, reverse_sort
from resources.sort_item import SortItem, SortItemModel
from resources.filter_text_item import FilterTextItem, FilterTextItemModel
from itgs import Itgs


class Emotion(BaseModel):
    word: str = Field(
        description="The unique word that represents this emotion, e.g., lost, angry, sad"
    )
    antonym: str = Field(
        description="The action that is taken to resolve this emotion, e.g., find yourself, calm down, cheer up"
    )


EMOTION_SORT_OPTIONS = [SortItem[Literal["word"], str]]
EmotionSortOption = (SortItemModel[Literal["word"], str],)


class EmotionFilter(BaseModel):
    word: Optional[FilterTextItemModel] = Field(
        None, description="the emotion that a class could resolve"
    )
    antonym: Optional[FilterTextItemModel] = Field(
        None, description="the action that resolves this emotion"
    )
    journey_uid: Optional[FilterTextItemModel] = Field(
        None, description="a uid of a journey that resolves this emotion"
    )


class ReadEmotionRequest(BaseModel):
    filters: EmotionFilter = Field(
        default_factory=EmotionFilter, description="the filters to apply"
    )
    sort: Optional[List[EmotionSortOption]] = Field(
        None, description="the order to sort by"
    )
    limit: int = Field(
        100, description="the maximum number of instructors to return", ge=1, le=1000
    )


class ReadEmotionResponse(BaseModel):
    items: List[Emotion] = Field(
        description="the items matching the filters in the given sort"
    )
    next_page_sort: Optional[List[EmotionSortOption]] = Field(
        description=(
            "if there is a next page or an earlier page, provides the necessary "
            "sort criteria to get it"
        )
    )


router = APIRouter()


@router.post(
    "/search", response_model=ReadEmotionResponse, responses=STANDARD_ERRORS_BY_CODE
)
async def read_emotions(
    args: ReadEmotionRequest, authorization: Optional[str] = Header(None)
):
    """Lists out emotions. This can also be used to fetch emotions which are on a
    particular journey.

    This requires standard authentication with an admin account.
    """
    sort = [srt.to_result() for srt in (args.sort or [])]
    sort = cleanup_sort(EMOTION_SORT_OPTIONS, sort, ["word"])
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
        items = await raw_read_emotions(itgs, filters_to_apply, sort, args.limit + 1)
        next_page_sort: Optional[List[SortItem]] = None
        last_item: Optional[Dict[str, Any]] = None
        if len(items) > args.limit:
            items = items[: args.limit]
            last_item = item_pseudocolumns(items[-1])
        first_item: Optional[Dict[str, Any]] = None
        if items and any(s.after is not None for s in sort):
            rev_sort = reverse_sort(sort, "make_exclusive")
            rev_items = await raw_read_emotions(itgs, filters_to_apply, rev_sort, 1)
            if rev_items:
                first_item = item_pseudocolumns(items[0])

        if first_item is not None or last_item is not None:
            next_page_sort = get_next_page_sort(first_item, last_item, sort)

        return Response(
            content=ReadEmotionResponse(
                items=items,
                next_page_sort=[s.to_model() for s in next_page_sort]
                if next_page_sort is not None
                else None,
            ).json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )


async def raw_read_emotions(
    itgs: Itgs,
    filters_to_apply: List[Tuple[str, Union[FilterItem, FilterTextItem]]],
    sort: List[SortItem],
    limit: int,
):
    """performs exactly the specified sort without pagination logic"""
    journey_uid_filter_idx = next(
        (idx for idx, f in enumerate(filters_to_apply) if f[0] == "journey_uid"), None
    )
    if journey_uid_filter_idx is not None:
        journey_uid_filter = filters_to_apply[journey_uid_filter_idx][1]
        filters_to_apply = filters_to_apply[:journey_uid_filter_idx] + (
            filters_to_apply[journey_uid_filter_idx + 1 :]
        )
    else:
        journey_uid_filter = None

    emotions = Table("emotions")
    journeys = Table("journeys")
    journey_emotions = Table("journey_emotions")

    query: QueryBuilder = Query.from_(emotions).select(
        emotions.word,
        emotions.antonym,
    )
    qargs = []

    def pseudocolumn(key: str) -> Term:
        if key in ("word", "antonym"):
            return emotions.field(key)
        raise ValueError(f"unknown key {key}")

    for key, filter in filters_to_apply:
        query = query.where(filter.applied_to(pseudocolumn(key), qargs))

    if journey_uid_filter is not None:
        query = query.where(
            ExistsCriterion(
                Query.from_(journey_emotions)
                .select(1)
                .join(journeys)
                .on(journeys.id == journey_emotions.journey_id)
                .where(journey_emotions.emotion_id == emotions.id)
                .where(journey_uid_filter.applied_to(journeys.uid, qargs))
            )
        )

    query = query.where(sort_criterion(sort, pseudocolumn, qargs))

    for srt in sort:
        query = query.orderby(pseudocolumn(srt.key), order=srt.order)

    query = query.limit(Parameter("?"))
    qargs.append(limit)

    conn = await itgs.conn()
    cursor = conn.cursor("none")
    response = await cursor.execute(query.get_sql(), qargs)
    items: List[Emotion] = []
    for row in response.results or []:
        items.append(Emotion(word=row[0]))
    return items


def item_pseudocolumns(item: Emotion) -> dict:
    """returns the dictified item such that the keys in the return dict match
    the keys of the sort options"""
    return item.dict()
