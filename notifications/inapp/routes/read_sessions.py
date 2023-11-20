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


class InappNotification(BaseModel):
    """An in-app notification as it's referenced by inapp notification user"""

    uid: str = Field(description="The UID of the inapp notification")
    name: str = Field(description="The internal name of the inapp notification")


class User(BaseModel):
    """A user as it's referenced by inapp notification user"""

    sub: str = Field(description="The sub of the user")


class InappNotificationUser(BaseModel):
    uid: str = Field(
        description="The UID of the relationship between the user and the inapp notification"
    )
    inapp_notification: InappNotification = Field(description="The inapp notification")
    user: User = Field(description="The user")
    platform: Literal["web", "ios", "android"] = Field(
        description="The platform the notification was seen on"
    )
    created_at: float = Field(
        description="When the relationship was created, in seconds since the epoch"
    )


INAPP_NOTIFICATION_USER_SORT_OPTIONS = [
    SortItem[Literal["uid"], str],
    SortItem[Literal["inapp_notification_uid"], str],
    SortItem[Literal["user_sub"], str],
    SortItem[Literal["platform"], str],
    SortItem[Literal["created_at"], float],
]
InappNotificationUserSortOption = Union[
    SortItemModel[Literal["uid"], str],
    SortItemModel[Literal["inapp_notification_uid"], str],
    SortItemModel[Literal["user_sub"], str],
    SortItemModel[Literal["platform"], str],
    SortItemModel[Literal["created_at"], float],
]


class InappNotificationUserFilter(BaseModel):
    uid: Optional[FilterTextItemModel] = Field(
        None, description="the uid of the relating row"
    )
    inapp_notification_uid: Optional[FilterTextItemModel] = Field(
        None, description="the uid of the inapp notification"
    )
    user_sub: Optional[FilterTextItemModel] = Field(
        None, description="the sub of the user"
    )
    platform: Optional[FilterTextItemModel] = Field(
        None, description="the platform the notification was seen on"
    )
    created_at: Optional[FilterItemModel[float]] = Field(
        None,
        description="when the relationship was created, in seconds since the epoch",
    )


class ReadInappNotificationUserRequest(BaseModel):
    filters: InappNotificationUserFilter = Field(
        default_factory=lambda: InappNotificationUserFilter.model_validate({}),
        description="the filters to apply",
    )
    sort: Optional[List[InappNotificationUserSortOption]] = Field(
        None, description="the order to sort by"
    )
    limit: int = Field(
        25, description="the maximum number of rows to return", ge=1, le=250
    )


class ReadInappNotificationUserResponse(BaseModel):
    items: List[InappNotificationUser] = Field(
        description="the items matching the filters in the given sort"
    )
    next_page_sort: Optional[List[InappNotificationUserSortOption]] = Field(
        description=(
            "if there is a next page or an earlier page, provides the necessary "
            "sort criteria to get it"
        )
    )


router = APIRouter()


@router.post(
    "/search_sessions",
    response_model=ReadInappNotificationUserResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_inapp_notification_users(
    args: ReadInappNotificationUserRequest, authorization: Optional[str] = Header(None)
):
    """Lists out the inapp notification / user relating rows. Each row corresponds
    to one user seeing a particular inapp notification. Thus, it's also reasonable
    to refer to it as a session a user had with a particular inapp notification,
    and the actions can be fetched using search_actions.

    Requires standard authentication with an admin account.
    """
    sort = [srt.to_result() for srt in (args.sort or [])]
    sort = cleanup_sort(INAPP_NOTIFICATION_USER_SORT_OPTIONS, sort, ["uid"])
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
        items = await raw_read_inapp_notification_users(
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
            rev_items = await raw_read_inapp_notification_users(
                itgs, filters_to_apply, rev_sort, 1
            )
            if rev_items:
                first_item = item_pseudocolumns(items[0])

        if first_item is not None or last_item is not None:
            next_page_sort = get_next_page_sort(first_item, last_item, sort)

        return Response(
            content=ReadInappNotificationUserResponse(
                items=items,
                next_page_sort=[s.to_model() for s in next_page_sort]
                if next_page_sort is not None
                else None,
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )


async def raw_read_inapp_notification_users(
    itgs: Itgs,
    filters_to_apply: List[Tuple[str, Union[FilterItem, FilterTextItem]]],
    sort: List[SortItem],
    limit: int,
):
    """performs exactly the specified sort without pagination logic"""
    inapp_notification_users = Table("inapp_notification_users")
    inapp_notifications = Table("inapp_notifications")
    users = Table("users")

    query: QueryBuilder = (
        Query.from_(inapp_notification_users)
        .select(
            inapp_notification_users.uid,
            inapp_notifications.uid,
            inapp_notifications.name,
            users.sub,
            inapp_notification_users.platform,
            inapp_notification_users.created_at,
        )
        .join(inapp_notifications)
        .on(inapp_notifications.id == inapp_notification_users.inapp_notification_id)
        .join(users)
        .on(users.id == inapp_notification_users.user_id)
    )
    qargs = []

    def pseudocolumn(key: str) -> Term:
        if key in ("uid", "platform", "created_at"):
            return inapp_notification_users.field(key)
        elif key == "inapp_notification_uid":
            return inapp_notifications.uid
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
    items: List[InappNotificationUser] = []
    for row in response.results or []:
        items.append(
            InappNotificationUser(
                uid=row[0],
                inapp_notification=InappNotification(
                    uid=row[1],
                    name=row[2],
                ),
                user=User(
                    sub=row[3],
                ),
                platform=row[4],
                created_at=row[5],
            )
        )
    return items


def item_pseudocolumns(item: InappNotificationUser) -> dict:
    """returns the dictified item such that the keys in the return dict match
    the keys of the sort options"""
    return {
        "uid": item.uid,
        "inapp_notification_uid": item.inapp_notification.uid,
        "user_sub": item.user.sub,
        "platform": item.platform,
        "created_at": item.created_at,
    }
