from pypika import Table, Query, Parameter
from pypika.queries import QueryBuilder
from pypika.terms import Term
from pypika.functions import Coalesce
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


class VipChatRequestAction(BaseModel):
    uid: str = Field(description="The UID of the vip chat request action")
    vip_chat_request_uid: str = Field(
        description="The UID of the vip chat request that this action is for"
    )
    action: Literal[
        "open", "click_cta", "click_x", "click_done", "close_window"
    ] = Field(description="The action that was performed")
    created_at: float = Field(
        description="The timestamp of when the action was performed"
    )
    relative_created_at: float = Field(
        description="The timestamp of when the action was performed, relative to the first open action"
    )


VIP_CHAT_REQUEST_ACTION_SORT_OPTIONS = [
    SortItem[Literal["uid"], str],
    SortItem[Literal["vip_chat_request_uid"], str],
    SortItem[Literal["action"], str],
    SortItem[Literal["created_at"], float],
    SortItem[Literal["relative_created_at"], float],
]
VipChatRequestActionSortOption = Union[
    SortItemModel[Literal["uid"], str],
    SortItemModel[Literal["vip_chat_request_uid"], str],
    SortItemModel[Literal["action"], str],
    SortItemModel[Literal["created_at"], float],
    SortItemModel[Literal["relative_created_at"], float],
]


class VipChatRequestActionFilter(BaseModel):
    uid: Optional[FilterTextItemModel] = Field(
        None, description="The UID of the vip chat request action"
    )
    vip_chat_request_uid: Optional[FilterTextItemModel] = Field(
        None, description="The UID of the vip chat request that this action is for"
    )
    action: Optional[FilterTextItemModel] = Field(
        None, description="The action that was performed"
    )
    created_at: Optional[FilterItemModel[float]] = Field(
        None, description="The timestamp of when the action was performed"
    )
    relative_created_at: Optional[FilterItemModel[float]] = Field(
        None,
        description="The timestamp of when the action was performed, relative to the first open action",
    )


class ReadVipChatRequestActionRequest(BaseModel):
    filters: VipChatRequestActionFilter = Field(
        default_factory=lambda: VipChatRequestActionFilter.model_validate({}),
        description="The filters to apply",
    )
    sort: Optional[List[VipChatRequestActionSortOption]] = Field(
        None, description="The sort options to apply"
    )
    limit: int = Field(
        25,
        description="The maximum number of vip chat request actions to return",
        ge=1,
        le=250,
    )


class ReadVipChatRequestActionResponse(BaseModel):
    items: List[VipChatRequestAction] = Field(
        description="the items matching the filters in the given sort"
    )
    next_page_sort: Optional[List[VipChatRequestActionSortOption]] = Field(
        description=(
            "if there is a next page or an earlier page, provides the necessary "
            "sort criteria to get it"
        )
    )


router = APIRouter()


@router.post(
    "/search",
    response_model=ReadVipChatRequestActionResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_vip_chat_request_actions(
    args: ReadVipChatRequestActionRequest, authorization: Optional[str] = Header(None)
):
    """Lists out vip chat request actions

    This requires standard authentication with an admin account.
    """
    sort = [srt.to_result() for srt in (args.sort or [])]
    sort = cleanup_sort(VIP_CHAT_REQUEST_ACTION_SORT_OPTIONS, sort, ["uid"])
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
        items = await raw_read_vip_chat_request_actions(
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
            rev_items = await raw_read_vip_chat_request_actions(
                itgs, filters_to_apply, rev_sort, 1
            )
            if rev_items:
                first_item = item_pseudocolumns(items[0])

        if first_item is not None or last_item is not None:
            next_page_sort = get_next_page_sort(first_item, last_item, sort)

        return Response(
            content=ReadVipChatRequestActionResponse(
                items=items,
                next_page_sort=[s.to_model() for s in next_page_sort]
                if next_page_sort is not None
                else None,
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )


async def raw_read_vip_chat_request_actions(
    itgs: Itgs,
    filters_to_apply: List[Tuple[str, Union[FilterItem, FilterTextItem]]],
    sort: List[SortItem],
    limit: int,
):
    """performs exactly the specified sort without pagination logic"""
    vip_chat_request_actions = Table("vip_chat_request_actions")
    vip_chat_requests = Table("vip_chat_requests")

    query: QueryBuilder = (
        Query.from_(vip_chat_request_actions)
        .select(
            vip_chat_request_actions.uid,
            vip_chat_requests.uid,
            vip_chat_request_actions.action,
            vip_chat_request_actions.created_at,
            (
                vip_chat_request_actions.created_at
                - Coalesce(vip_chat_requests.popup_seen_at, 0)
            ).as_("relative_created_at"),
        )
        .join(vip_chat_requests)
        .on(vip_chat_requests.id == vip_chat_request_actions.vip_chat_request_id)
    )
    qargs = []

    def pseudocolumn(key: str) -> Term:
        if key in ("uid", "action", "created_at"):
            return vip_chat_request_actions.field(key)
        elif key == "vip_chat_request_uid":
            return vip_chat_requests.field("uid")
        elif key == "relative_created_at":
            return vip_chat_request_actions.created_at - Coalesce(
                vip_chat_requests.popup_seen_at, 0
            )

        raise ValueError(f"unknown key {key}")

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
    items: List[VipChatRequestAction] = []
    for row in response.results or []:
        items.append(
            VipChatRequestAction(
                uid=row[0],
                vip_chat_request_uid=row[1],
                action=row[2],
                created_at=row[3],
                relative_created_at=row[4],
            )
        )
    return items


def item_pseudocolumns(item: VipChatRequestAction) -> dict:
    """returns the dictified item such that the keys in the return dict match
    the keys of the sort options"""
    return item.model_dump()
