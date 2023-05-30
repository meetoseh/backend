from pypika import Table, Query, Parameter
from pypika.queries import QueryBuilder
from pypika.terms import Term, Case, ExistsCriterion
from pypika.functions import Coalesce, Max
from typing import Any, Dict, List, Literal, Optional, Set, Tuple, Union
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
import image_files.auth as img_file_auth
from itgs import Itgs
from users.lib.models import User

USER_SORT_OPTIONS = [
    SortItem[Literal["sub"], str],
    SortItem[Literal["email"], str],
    SortItem[Literal["created_at"], float],
    SortItem[Literal["last_seen_at"], float],
]
UserSortOption = Union[
    SortItemModel[Literal["sub"], str],
    SortItemModel[Literal["email"], str],
    SortItemModel[Literal["created_at"], float],
    SortItemModel[Literal["last_seen_at"], float],
]


class UserFilter(BaseModel):
    sub: Optional[FilterTextItemModel] = Field(
        None, description="the unique identifier of the user"
    )
    email: Optional[FilterTextItemModel] = Field(
        None, description="the email of the user"
    )
    email_verified: Optional[FilterItemModel[bool]] = Field(
        None, description="whether or not the user has verified their email"
    )
    phone_number: Optional[FilterTextItemModel] = Field(
        None, description="the phone number of the user"
    )
    phone_number_verified: Optional[FilterItemModel[bool]] = Field(
        None, description="whether or not the user has verified their phone number"
    )
    given_name: Optional[FilterTextItemModel] = Field(
        None, description="the first name of the user"
    )
    family_name: Optional[FilterTextItemModel] = Field(
        None, description="the last name of the user"
    )
    name: Optional[FilterTextItemModel] = Field(
        None,
        description="the full name of the user formed by concatenating the first and last names",
    )
    admin: Optional[FilterItemModel[bool]] = Field(
        None, description="whether or not the user is an admin"
    )
    revenue_cat_id: Optional[FilterTextItemModel] = Field(
        None, description="the revenue cat id of the user"
    )
    primary_interest: Optional[FilterTextItemModel] = Field(
        None, description="the users primary interest"
    )
    utm: Optional[FilterTextItemModel] = Field(
        None,
        description=(
            "if specified, the canonical query representation of at least one utm the user "
            "has clicked on before signing up must match to be included in the result"
        ),
    )
    created_at: Optional[FilterItemModel[float]] = Field(
        None, description="the time at which the user was created"
    )
    last_seen_at: Optional[FilterItemModel[float]] = Field(
        None, description="the time at which the user was last seen"
    )


class ReadUserRequest(BaseModel):
    filters: UserFilter = Field(
        default_factory=UserFilter, description="the filters to apply"
    )
    sort: Optional[List[UserSortOption]] = Field(
        None, description="the order to sort by"
    )
    limit: int = Field(
        10, description="the maximum number of users to return", ge=1, le=100
    )


class ReadUserResponse(BaseModel):
    items: List[User] = Field(
        description="the items matching the filters in the given sort"
    )
    next_page_sort: Optional[List[UserSortOption]] = Field(
        description=(
            "if there is a next page or an earlier page, provides the necessary "
            "sort criteria to get it"
        )
    )


router = APIRouter()


@router.post(
    "/search", response_model=ReadUserResponse, responses=STANDARD_ERRORS_BY_CODE
)
async def read_users(
    args: ReadUserRequest, authorization: Optional[str] = Header(None)
):
    """Lists out users

    This requires standard authentication with an admin account.
    """
    sort = [srt.to_result() for srt in (args.sort or [])]
    sort = cleanup_sort(USER_SORT_OPTIONS, sort, ["sub"])
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
        items = await raw_read_users(itgs, filters_to_apply, sort, args.limit + 1)
        next_page_sort: Optional[List[SortItem]] = None
        last_item: Optional[Dict[str, Any]] = None
        if len(items) > args.limit:
            items = items[: args.limit]
            last_item = item_pseudocolumns(items[-1])
        first_item: Optional[Dict[str, Any]] = None
        if items and any(s.after is not None for s in sort):
            rev_sort = reverse_sort(sort, "make_exclusive")
            rev_items = await raw_read_users(itgs, filters_to_apply, rev_sort, 1)
            if rev_items:
                first_item = item_pseudocolumns(items[0])

        if first_item is not None or last_item is not None:
            next_page_sort = get_next_page_sort(first_item, last_item, sort)

        return Response(
            content=ReadUserResponse(
                items=items,
                next_page_sort=[s.to_model() for s in next_page_sort]
                if next_page_sort is not None
                else None,
            ).json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )


base_keys: Set[str] = frozenset(
    (
        "sub",
        "email",
        "email_verified",
        "phone_number",
        "phone_number_verified",
        "given_name",
        "family_name",
        "admin",
        "revenue_cat_id",
        "created_at",
    )
)


async def raw_read_users(
    itgs: Itgs,
    filters_to_apply: List[Tuple[str, Union[FilterItem, FilterTextItem]]],
    sort: List[SortItem],
    limit: int,
):
    """performs exactly the specified sort without pagination logic"""
    users = Table("users")
    user_profile_pictures = Table("user_profile_pictures")
    visitor_users = Table("visitor_users")
    image_files = Table("image_files")
    user_interests = Table("user_interests")
    interests = Table("interests")

    last_seen_ats = Table("last_seen_ats")

    query: QueryBuilder = (
        Query.with_(
            Query.from_(visitor_users)
            .select(
                visitor_users.user_id.as_("user_id"),
                Max(visitor_users.last_seen_at).as_("last_seen_at"),
            )
            .groupby(visitor_users.user_id),
            last_seen_ats.get_table_name(),
        )
        .from_(users)
        .select(
            users.sub,
            users.email,
            users.email_verified,
            users.phone_number,
            users.phone_number_verified,
            users.given_name,
            users.family_name,
            users.admin,
            users.revenue_cat_id,
            image_files.uid,
            users.created_at,
            Coalesce(last_seen_ats.last_seen_at, users.created_at).as_("last_seen_at"),
        )
        .left_outer_join(user_profile_pictures)
        .on(
            (user_profile_pictures.user_id == users.id)
            & (user_profile_pictures.latest == 1)
        )
        .left_outer_join(image_files)
        .on(image_files.id == user_profile_pictures.image_file_id)
        .left_outer_join(last_seen_ats)
        .on(last_seen_ats.user_id == users.id)
    )
    qargs = []

    joined_interests = False
    if any(k == "primary_interest" for (k, _) in filters_to_apply):
        joined_interests = True
        query = query.left_outer_join(user_interests).on(
            (user_interests.user_id == users.id) & (user_interests.is_primary == 1)
        )
        query = query.left_outer_join(interests).on(
            interests.id == user_interests.interest_id
        )

    def pseudocolumn(key: str) -> Term:
        if key in base_keys:
            return users.field(key)
        elif key == "last_seen_at":
            return last_seen_ats.field(key)
        elif key == "name":
            return (
                Case()
                .when(
                    users.field("given_name").isnotnull()
                    & users.field("family_name").isnotnull(),
                    sqlite_string_concat(
                        users.given_name, sqlite_string_concat(" ", users.family_name)
                    ),
                )
                .when(users.field("given_name").isnotnull(), users.given_name)
                .when(users.field("family_name").isnotnull(), users.family_name)
                .else_(Term.wrap_constant(None))
            )
        elif key == "primary_interest":
            assert joined_interests
            return interests.slug
        raise ValueError(f"unknown key {key}")

    def utm_term(filter: FilterTextItem, qargs: list) -> Term:
        utms = Table("utms").as_("utm_term_utms")
        visitor_utms = Table("visitor_utms").as_("utm_term_visitor_utms")
        visitor_users = Table("visitor_users").as_("utm_term_visitor_users")
        return ExistsCriterion(
            Query.from_(utms)
            .join(visitor_utms)
            .on(visitor_utms.utm_id == utms.id)
            .join(visitor_users)
            .on(visitor_users.visitor_id == visitor_utms.visitor_id)
            .select(1)
            .where(visitor_users.user_id == users.id)
            .where(visitor_utms.clicked_at <= users.created_at)
            .where(filter.applied_to(utms.canonical_query_param, qargs))
        )

    for key, filter in filters_to_apply:
        if key == "utm":
            query = query.where(utm_term(filter, qargs))
        else:
            query = query.where(filter.applied_to(pseudocolumn(key), qargs))

    query = query.where(sort_criterion(sort, pseudocolumn, qargs))

    for srt in sort:
        query = query.orderby(pseudocolumn(srt.key), order=srt.order)

    query = query.limit(Parameter("?"))
    qargs.append(limit)

    conn = await itgs.conn()
    cursor = conn.cursor("none")
    response = await cursor.execute(query.get_sql(), qargs)
    items: List[User] = []
    for row in response.results or []:
        image_file_uid: Optional[str] = row[9]
        image_file_ref: Optional[ImageFileRef] = None
        if image_file_uid is not None:
            image_file_jwt = await img_file_auth.create_jwt(itgs, image_file_uid)
            image_file_ref = ImageFileRef(uid=image_file_uid, jwt=image_file_jwt)

        items.append(
            User(
                sub=row[0],
                email=row[1],
                email_verified=bool(row[2]),
                phone_number=row[3],
                phone_number_verified=bool(row[4]),
                given_name=row[5],
                family_name=row[6],
                admin=bool(row[7]),
                revenue_cat_id=row[8],
                profile_picture=image_file_ref,
                created_at=row[10],
                last_seen_at=row[11],
            )
        )
    return items


def item_pseudocolumns(item: User) -> dict:
    """returns the dictified item such that the keys in the return dict match
    the keys of the sort options"""
    return {
        "sub": item.sub,
        "email": item.email,
        "created_at": item.created_at,
        "last_seen_at": item.last_seen_at,
    }
