from pypika import Table, Query, Parameter
from pypika.queries import QueryBuilder
from pypika.terms import Term
from typing import Any, Dict, List, Literal, Optional, Tuple, Union
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from auth import auth_admin
from db.utils import sqlite_string_concat
from models import STANDARD_ERRORS_BY_CODE
from resources.filter import sort_criterion, flattened_filters
from resources.filter_item import FilterItem, FilterItemModel
from resources.sort import cleanup_sort, get_next_page_sort, reverse_sort
from resources.sort_item import SortItem, SortItemModel
from resources.filter_text_item import FilterTextItem, FilterTextItemModel
from image_files.models import ImageFileRef
from itgs import Itgs
from vip_chat_requests.routes.create import (
    User,
    Phone04102023VariantInternal,
    Phone04102023VariantAdmin,
)
from image_files.auth import create_jwt as create_image_file_jwt


class VipChatRequest(BaseModel):
    uid: str = Field(
        description="The primary stable external identifier for this vip chat request"
    )
    user: User = Field(description="The user who should recieve the chat request")
    added_by_user: Optional[User] = Field(
        description="The user who created this chat request, if known"
    )
    variant: Literal["phone-04102023"] = Field(
        description="Which prompt to show the user"
    )
    display_data: Phone04102023VariantAdmin = Field(
        description="The display data, which depends on the variant"
    )
    reason: Optional[str] = Field(
        description="Why we are sending this chat request. This is for debugging purposes only."
    )
    created_at: float = Field(
        description="The time the chat request was created in seconds since the epoch"
    )
    popup_seen_at: Optional[float] = Field(
        description="The time the popup was seen by the user in seconds since the epoch"
    )


VIP_CHAT_REQUEST_SORT_OPTIONS = [
    SortItem[Literal["uid"], str],
    SortItem[Literal["user_email"], str],
    SortItem[Literal["created_at"], float],
    SortItem[Literal["popup_seen_at"], float],
]
VipChatRequestSortOption = Union[
    SortItemModel[Literal["uid"], str],
    SortItemModel[Literal["user_email"], str],
    SortItemModel[Literal["created_at"], float],
    SortItemModel[Literal["popup_seen_at"], float],
]


class VipChatRequestFilter(BaseModel):
    uid: Optional[FilterTextItemModel] = Field(
        None, description="The uid of the vip chat request"
    )
    user_sub: Optional[FilterTextItemModel] = Field(
        None, description="The sub of the user who should recieve the chat request"
    )
    user_email: Optional[FilterTextItemModel] = Field(
        None,
        description="The email address of the user who should recieve the chat request",
    )
    user_name: Optional[FilterTextItemModel] = Field(
        None, description="The name of the user who should recieve the chat request"
    )
    variant: Optional[FilterTextItemModel] = Field(
        None, description="The variant of the vip chat request"
    )
    created_at: Optional[FilterItemModel[float]] = Field(
        None,
        description="The time the chat request was created in seconds since the epoch",
    )
    popup_seen_at: Optional[FilterItemModel[float]] = Field(
        None,
        description="The time the popup was seen by the user in seconds since the epoch",
    )


class ReadVipChatRequestRequest(BaseModel):
    filters: VipChatRequestFilter = Field(
        default_factory=VipChatRequestFilter, description="The filters to apply"
    )
    sort: Optional[List[VipChatRequestSortOption]] = Field(
        None, description="The sort order to apply"
    )
    limit: int = Field(
        25,
        description="The maximum number of vip chat requests to return",
        ge=1,
        le=250,
    )


class ReadVipChatRequestResponse(BaseModel):
    items: List[VipChatRequest] = Field(
        description="the items matching the filters in the given sort"
    )
    next_page_sort: Optional[List[VipChatRequestSortOption]] = Field(
        description=(
            "if there is a next page or an earlier page, provides the necessary "
            "sort criteria to get it"
        )
    )


router = APIRouter()


@router.post(
    "/search",
    response_model=ReadVipChatRequestResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_vip_chat_requests(
    args: ReadVipChatRequestRequest, authorization: Optional[str] = Header(None)
):
    """Lists out vip chat requests

    This requires standard authorization with an admin account
    """
    sort = [srt.to_result() for srt in (args.sort or [])]
    sort = cleanup_sort(VIP_CHAT_REQUEST_SORT_OPTIONS, sort, ["uid"])
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
        items = await raw_read_vip_chat_requests(
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
            rev_items = await raw_read_vip_chat_requests(
                itgs, filters_to_apply, rev_sort, 1
            )
            if rev_items:
                first_item = item_pseudocolumns(items[0])

        if first_item is not None or last_item is not None:
            next_page_sort = get_next_page_sort(first_item, last_item, sort)

        return Response(
            content=ReadVipChatRequestResponse(
                items=items,
                next_page_sort=[s.to_model() for s in next_page_sort]
                if next_page_sort is not None
                else None,
            ).json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )


async def raw_read_vip_chat_requests(
    itgs: Itgs,
    filters_to_apply: List[Tuple[str, Union[FilterItem, FilterTextItem]]],
    sort: List[SortItem],
    limit: int,
):
    """performs exactly the specified sort without pagination logic"""
    vip_chat_requests = Table("vip_chat_requests")
    users = Table("users")
    added_by_users = users.as_("added_by_users")

    query: QueryBuilder = (
        Query.from_(vip_chat_requests)
        .select(
            vip_chat_requests.uid,
            users.sub,
            users.given_name,
            users.family_name,
            users.email,
            users.created_at,
            added_by_users.sub,
            added_by_users.given_name,
            added_by_users.family_name,
            added_by_users.email,
            added_by_users.created_at,
            vip_chat_requests.variant,
            vip_chat_requests.display_data,
            vip_chat_requests.reason,
            vip_chat_requests.created_at,
            vip_chat_requests.popup_seen_at,
        )
        .join(users)
        .on(users.id == vip_chat_requests.user_id)
        .left_outer_join(added_by_users)
        .on(added_by_users.id == vip_chat_requests.added_by_user_id)
    )
    qargs = []

    def pseudocolumn(key: str) -> Term:
        if key in ("uid", "variant", "reason", "created_at", "popup_seen_at"):
            return vip_chat_requests.field(key)
        elif key in (
            "user_sub",
            "user_given_name",
            "user_family_name",
            "user_email",
            "user_created_at",
        ):
            return users.field(key[5:])
        elif key == "user_name":
            return sqlite_string_concat(
                sqlite_string_concat(users.given_name, " "), users.family_name
            )
        elif key in (
            "added_by_user_sub",
            "added_by_user_given_name",
            "added_by_user_family_name",
            "added_by_user_email",
            "added_by_user_created_at",
        ):
            return added_by_users.field(key[14:])

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
    items: List[VipChatRequest] = []
    for row in response.results or []:
        uid: str = row[0]
        user = User(
            sub=row[1],
            given_name=row[2],
            family_name=row[3],
            email=row[4],
            created_at=row[5],
        )
        added_by_user = (
            None
            if row[6] is None
            else User(
                sub=row[6],
                given_name=row[7],
                family_name=row[8],
                email=row[9],
                created_at=row[10],
            )
        )
        variant: str = row[11]
        raw_display_data: str = row[12]
        reason: str = row[13]
        created_at: float = row[14]
        popup_seen_at: Optional[float] = row[15]

        if variant != "phone-04102023":
            raise ValueError(f"unsupported {variant=}")

        parsed_display_data = Phone04102023VariantInternal.parse_raw(
            raw_display_data, content_type="application/json"
        )

        items.append(
            VipChatRequest(
                uid=uid,
                user=user,
                added_by_user=added_by_user,
                variant=variant,
                display_data=Phone04102023VariantAdmin(
                    phone_number=parsed_display_data.phone_number,
                    text_prefill=parsed_display_data.text_prefill,
                    background_image=ImageFileRef(
                        uid=parsed_display_data.background_image_uid,
                        jwt=await create_image_file_jwt(
                            itgs, parsed_display_data.background_image_uid
                        ),
                    ),
                    image=ImageFileRef(
                        uid=parsed_display_data.image_uid,
                        jwt=await create_image_file_jwt(
                            itgs, parsed_display_data.image_uid
                        ),
                    ),
                    image_caption=parsed_display_data.image_caption,
                    title=parsed_display_data.title,
                    message=parsed_display_data.message,
                    cta=parsed_display_data.cta,
                ),
                reason=reason,
                created_at=created_at,
                popup_seen_at=popup_seen_at,
            )
        )

    return items


def item_pseudocolumns(item: VipChatRequest) -> dict:
    """returns the dictified item such that the keys in the return dict match
    the keys of the sort options"""
    return {
        "uid": item.uid,
        "user_email": item.user.email,
        "created_at": item.created_at,
        "popup_seen_at": item.popup_seen_at,
    }
