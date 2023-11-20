import json
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

CONTACT_METHOD_LOG_SORT_OPTIONS: Tuple[type, ...] = (
    SortItem[Literal["uid"], str],
    SortItem[Literal["user_sub"], str],
    SortItem[Literal["created_at"], float],
)
ContactMethodLogSortOption = Union[
    SortItemModel[Literal["uid"], str],
    SortItemModel[Literal["user_sub"], str],
    SortItemModel[Literal["created_at"], float],
]


class ContactMethodLog(BaseModel):
    uid: str = Field(description="the row identifier")
    user_sub: str = Field(description="the unique identifier of the user")
    channel: Literal["email", "phone", "push"] = Field(
        description="the channel of the contact method"
    )
    identifier: str = Field(
        description="the identifier of the contact method, e.g., the phone number"
    )
    action: Literal[
        "create_verified",
        "create_unverified",
        "delete",
        "verify",
        "enable_notifs",
        "disable_notifs",
    ] = Field(description="the action taken on the contact method")
    reason: dict = Field(description="the debug reason associated with the entry")
    created_at: float = Field(description="the time the log entry was inserted")


class ContactMethodLogFilter(BaseModel):
    uid: Optional[FilterTextItemModel] = Field(None, description="the row identifier")
    user_sub: Optional[FilterTextItemModel] = Field(
        None, description="the unique identifier of the user"
    )
    channel: Optional[FilterTextItemModel] = Field(
        None, description="the channel of the contact method, e.g., phone"
    )
    identifier: Optional[FilterTextItemModel] = Field(
        None, description="the identifier of the contact method, e.g., the phone number"
    )
    action: Optional[FilterTextItemModel] = Field(
        None,
        description="the action taken on the contact method, e.g., create_verified",
    )
    created_at: Optional[FilterItemModel[float]] = Field(
        None, description="the time the log entry was inserted"
    )

    def __init__(
        self,
        *,
        uid: Optional[FilterTextItemModel] = None,
        user_sub: Optional[FilterTextItemModel] = None,
        channel: Optional[FilterTextItemModel] = None,
        identifier: Optional[FilterTextItemModel] = None,
        action: Optional[FilterTextItemModel] = None,
        created_at: Optional[FilterItemModel[float]] = None,
    ):
        return super().__init__(
            uid=uid,
            user_sub=user_sub,
            channel=channel,
            identifier=identifier,
            action=action,
            created_at=created_at,
        )


class ReadContactMethodLogRequest(BaseModel):
    filters: ContactMethodLogFilter = Field(
        default_factory=ContactMethodLogFilter, description="the filters to apply"
    )
    sort: Optional[List[ContactMethodLogSortOption]] = Field(
        None, description="the order to sort by"
    )
    limit: int = Field(
        10, description="the maximum number of entries to return", ge=1, le=100
    )


class ReadContactMethodLogResponse(BaseModel):
    items: List[ContactMethodLog] = Field(
        description="the items matching the filters in the given sort"
    )
    next_page_sort: Optional[List[ContactMethodLogSortOption]] = Field(
        description=(
            "if there is a next page or an earlier page, provides the necessary "
            "sort criteria to get it"
        )
    )


router = APIRouter()


@router.post(
    "/contact_method",
    response_model=ReadContactMethodLogResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_contact_method_log(
    args: ReadContactMethodLogRequest, authorization: Optional[str] = Header(None)
):
    """Reads from the contact method log

    This requires standard authentication with an admin account.
    """
    sort = [srt.to_result() for srt in (args.sort or [])]
    sort = cleanup_sort(CONTACT_METHOD_LOG_SORT_OPTIONS, sort, ["uid"])
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
        items = await raw_read_contact_method_log(
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
            rev_items = await raw_read_contact_method_log(
                itgs, filters_to_apply, rev_sort, 1
            )
            if rev_items:
                first_item = item_pseudocolumns(items[0])

        if first_item is not None or last_item is not None:
            next_page_sort = get_next_page_sort(first_item, last_item, sort)

        return Response(
            content=ReadContactMethodLogResponse(
                items=items,
                next_page_sort=[s.to_model() for s in next_page_sort]
                if next_page_sort is not None
                else None,
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )


async def raw_read_contact_method_log(
    itgs: Itgs,
    filters_to_apply: List[Tuple[str, Union[FilterItem, FilterTextItem]]],
    sort: List[SortItem],
    limit: int,
):
    """performs exactly the specified sort without pagination logic"""
    contact_method_log = Table("contact_method_log")
    users = Table("users")

    query: QueryBuilder = (
        Query.from_(contact_method_log)
        .select(
            contact_method_log.uid,
            users.sub,
            contact_method_log.channel,
            contact_method_log.identifier,
            contact_method_log.action,
            contact_method_log.reason,
            contact_method_log.created_at,
        )
        .join(users)
        .on(users.id == contact_method_log.user_id)
    )
    qargs = []

    def pseudocolumn(key: str) -> Term:
        if key in ("uid", "channel", "identifier", "action", "reason", "created_at"):
            return contact_method_log.field(key)
        elif key == "user_sub":
            return users.sub
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
    items: List[ContactMethodLog] = []
    for row in response.results or []:
        items.append(
            ContactMethodLog(
                uid=row[0],
                user_sub=row[1],
                channel=row[2],
                identifier=row[3],
                action=row[4],
                reason=json.loads(row[5]),
                created_at=row[6],
            )
        )
    return items


def item_pseudocolumns(item: ContactMethodLog) -> dict:
    """returns the dictified item such that the keys in the return dict match
    the keys of the sort options"""
    return {
        "uid": item.uid,
        "user_sub": item.user_sub,
        "created_at": item.created_at,
    }
