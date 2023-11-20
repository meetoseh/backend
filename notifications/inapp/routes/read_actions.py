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


class InappNotificationAction(BaseModel):
    """The information about an inapp notification action when referenced within
    an inapp notification user action
    """

    uid: str = Field(description="The UID of the action")
    slug: str = Field(
        description="The slug of the action as its referenced by the frontend"
    )


class InappNotificationUserAction(BaseModel):
    """An action taken by a user within an in-app notification"""

    uid: str = Field(description="The UID identifying this record")
    inapp_notification_user_uid: str = Field(description="The UID of the session")
    user_sub: str = Field(description="The sub of the user who took the action")
    inapp_notification_action: InappNotificationAction = Field(
        description="The action taken"
    )
    extra: Optional[Dict[str, Any]] = Field(
        description="Extra information about the action, if any"
    )
    created_at: float = Field(
        description="When the action was taken, in seconds since the epoch"
    )


INAPP_NOTIFICATION_USER_ACTION_SORT_OPTIONS = [
    SortItem[Literal["uid"], str],
    SortItem[Literal["inapp_notification_user_uid"], str],
    SortItem[Literal["user_sub"], str],
    SortItem[Literal["created_at"], float],
]
InappNotificationUserActionSortOption = Union[
    SortItemModel[Literal["uid"], str],
    SortItemModel[Literal["inapp_notification_user_uid"], str],
    SortItemModel[Literal["user_sub"], str],
    SortItemModel[Literal["created_at"], float],
]


class InappNotificationUserActionFilter(BaseModel):
    uid: Optional[FilterTextItemModel] = Field(None, description="the uid of the row")
    inapp_notification_user_uid: Optional[FilterTextItemModel] = Field(
        None, description="the uid of the related inapp notification user"
    )
    user_sub: Optional[FilterTextItemModel] = Field(
        None, description="the sub of the user who took the action"
    )
    action_uid: Optional[FilterTextItemModel] = Field(
        None, description="the uid of the action taken"
    )
    action_slug: Optional[FilterTextItemModel] = Field(
        None, description="the slug of the action taken"
    )
    created_at: Optional[FilterItemModel[float]] = Field(
        None, description="when the action was taken, in seconds since the epoch"
    )


class ReadInappNotificationUserActionRequest(BaseModel):
    filters: InappNotificationUserActionFilter = Field(
        default_factory=lambda: InappNotificationUserActionFilter.model_validate({}),
        description="the filters to apply",
    )
    sort: Optional[List[InappNotificationUserActionSortOption]] = Field(
        None, description="the order to sort by"
    )
    limit: int = Field(
        25, description="the maximum number of rows to return", ge=1, le=250
    )


class ReadInappNotificationUserActionResponse(BaseModel):
    items: List[InappNotificationUserAction] = Field(
        description="the items matching the filters in the given sort"
    )
    next_page_sort: Optional[List[InappNotificationUserActionSortOption]] = Field(
        description=(
            "if there is a next page or an earlier page, provides the necessary "
            "sort criteria to get it"
        )
    )


router = APIRouter()


@router.post(
    "/search_actions",
    response_model=ReadInappNotificationUserActionResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_inapp_notification_user_acctions(
    args: ReadInappNotificationUserActionRequest,
    authorization: Optional[str] = Header(None),
):
    """Lists out actions that users took within inapp notification sessions.

    Requires standard authentication with an admin account.
    """
    sort = [srt.to_result() for srt in (args.sort or [])]
    sort = cleanup_sort(INAPP_NOTIFICATION_USER_ACTION_SORT_OPTIONS, sort, ["uid"])
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
        items = await raw_read_inapp_notification_user_actions(
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
            rev_items = await raw_read_inapp_notification_user_actions(
                itgs, filters_to_apply, rev_sort, 1
            )
            if rev_items:
                first_item = item_pseudocolumns(items[0])

        if first_item is not None or last_item is not None:
            next_page_sort = get_next_page_sort(first_item, last_item, sort)

        return Response(
            content=ReadInappNotificationUserActionResponse(
                items=items,
                next_page_sort=[s.to_model() for s in next_page_sort]
                if next_page_sort is not None
                else None,
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )


async def raw_read_inapp_notification_user_actions(
    itgs: Itgs,
    filters_to_apply: List[Tuple[str, Union[FilterItem, FilterTextItem]]],
    sort: List[SortItem],
    limit: int,
):
    """performs exactly the specified sort without pagination logic"""
    inapp_notification_user_actions = Table("inapp_notification_user_actions")
    inapp_notification_users = Table("inapp_notification_users")
    inapp_notification_actions = Table("inapp_notification_actions")
    users = Table("users")

    query: QueryBuilder = (
        Query.from_(inapp_notification_user_actions)
        .select(
            inapp_notification_user_actions.uid,
            inapp_notification_users.uid,
            users.sub,
            inapp_notification_actions.uid,
            inapp_notification_actions.slug,
            inapp_notification_user_actions.extra,
            inapp_notification_user_actions.created_at,
        )
        .join(inapp_notification_users)
        .on(
            inapp_notification_users.id
            == inapp_notification_user_actions.inapp_notification_user_id
        )
        .join(users)
        .on(users.id == inapp_notification_users.user_id)
        .join(inapp_notification_actions)
        .on(
            inapp_notification_actions.id
            == inapp_notification_user_actions.inapp_notification_action_id
        )
    )
    qargs = []

    def pseudocolumn(key: str) -> Term:
        if key in ("uid", "created_at"):
            return inapp_notification_user_actions.field(key)
        elif key == "inapp_notification_user_uid":
            return inapp_notification_users.uid
        elif key == "user_sub":
            return users.sub
        elif key == "action_uid":
            return inapp_notification_actions.uid
        elif key == "action_slug":
            return inapp_notification_actions.slug
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
    items: List[InappNotificationUserAction] = []
    for row in response.results or []:
        items.append(
            InappNotificationUserAction(
                uid=row[0],
                inapp_notification_user_uid=row[1],
                user_sub=row[2],
                inapp_notification_action=InappNotificationAction(
                    uid=row[3], slug=row[4]
                ),
                extra=(json.loads(row[5]) if row[5] is not None else None),
                created_at=row[6],
            )
        )
    return items


def item_pseudocolumns(item: InappNotificationUserAction) -> dict:
    """returns the dictified item such that the keys in the return dict match
    the keys of the sort options"""
    return {
        "uid": item.uid,
        "inapp_notification_user_uid": item.inapp_notification_user_uid,
        "user_sub": item.user_sub,
        "created_at": item.created_at,
    }
