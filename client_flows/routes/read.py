import json
from pypika import Table, Query, Parameter
from pypika.queries import QueryBuilder
from pypika.terms import Term
from client_flows.lib.parse_flow_screens import decode_flow_screens
from typing import Any, Dict, List, Literal, Optional, Tuple, Union, cast
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from auth import auth_admin
from lib.client_flows.client_flow_rule import ClientFlowRules, client_flow_rules_adapter
from lib.client_flows.client_flow_screen import ClientFlowScreen
from models import STANDARD_ERRORS_BY_CODE
from resources.filter import sort_criterion, flattened_filters
from resources.filter_bit_field_item import FilterBitFieldItemModel
from resources.filter_item import FilterItemModel
from resources.filter_item_like import FilterItemLike
from resources.sort import cleanup_sort, get_next_page_sort, reverse_sort
from resources.sort_item import SortItem, SortItemModel
from resources.filter_text_item import FilterTextItemModel
from itgs import Itgs


class ClientFlow(BaseModel):
    uid: str = Field(description="Primary stable external row identifier")
    slug: str = Field(description="Semantic identifier for when this flow is triggered")
    name: Optional[str] = Field(None, description="Human-readable name for this flow")
    description: Optional[str] = Field(
        None, description="Human-readable description for this flow"
    )
    client_schema: dict = Field(
        description=(
            "A valid openapi 3.0.3 schema object describing the expected "
            "client parameters when triggering this flow.\n\n"
            "https://spec.openapis.org/oas/v3.0.3#schema-object"
        )
    )
    server_schema: dict = Field(
        description=(
            "A valid openapi 3.0.3 schema object describing the expected "
            "server parameters when triggering this flow.\n\n"
            "https://spec.openapis.org/oas/v3.0.3#schema-object"
        )
    )
    replaces: bool = Field(
        description=(
            "True if the users client screen queue is cleared before adding "
            "the screens, false if the screens are just prepended"
        )
    )
    screens: List[ClientFlowScreen] = Field(
        description=(
            "The screens that are prepended to the users client screen queue "
            "when this flow is triggered"
        )
    )
    rules: ClientFlowRules = Field(
        description=("The rules that are checked when this flow is triggered")
    )
    flags: int = Field(
        description="64-bit signed integer, where each bit represents a boolean flag, which, from lowest to highest:\n"
        "- `1 << 0`: shows in admin: by default, the admin client filters to those with this bit set\n"
        "- `1 << 1`: custom: if not set, deleting and changing the slug is prevented\n"
        "- `1 << 2`: ios triggerable: if not set, replaced with forbidden if triggered on ios\n"
        "- `1 << 3`: android triggerable: if not set, replaced with forbidden when triggered on android\n"
        "- `1 << 4`: browser triggerable: if not set, replaced with forbidden when triggered on web\n"
    )
    created_at: float = Field(
        description="When this record was created in seconds since the unix epoch"
    )


CLIENT_FLOW_SORT_OPTIONS = [
    SortItem[Literal["uid"], str],
    SortItem[Literal["slug"], str],
    SortItem[Literal["created_at"], float],
]
ClientFlowSortOption = Union[
    SortItemModel[Literal["uid"], str],
    SortItemModel[Literal["slug"], str],
    SortItemModel[Literal["created_at"], float],
]


class ClientFlowFilter(BaseModel):
    uid: Optional[FilterTextItemModel] = Field(
        None, description="primary stable identifier"
    )
    slug: Optional[FilterTextItemModel] = Field(None, description="semantic identifier")
    name: Optional[FilterTextItemModel] = Field(
        None, description="human-readable name, not necessarily unique"
    )
    flags: Optional[FilterBitFieldItemModel] = Field(None, description="boolean flags")
    created_at: Optional[FilterItemModel[float]] = Field(
        None, description="when this record was created, seconds since unix epoch"
    )


class ReadClientFlowRequest(BaseModel):
    filters: ClientFlowFilter = Field(
        default_factory=lambda: ClientFlowFilter.model_validate({}),
        description="the filters to apply",
    )
    sort: Optional[List[ClientFlowSortOption]] = Field(
        None, description="the order to sort by"
    )
    limit: int = Field(
        100, description="the maximum number of items to return", ge=1, le=1000
    )


class ReadClientFlowResponse(BaseModel):
    items: List[ClientFlow] = Field(
        description="the items matching the filters in the given sort"
    )
    next_page_sort: Optional[List[ClientFlowSortOption]] = Field(
        description=(
            "if there is a next page or an earlier page, provides the necessary "
            "sort criteria to get it"
        )
    )


router = APIRouter()


@router.post(
    "/search", response_model=ReadClientFlowResponse, responses=STANDARD_ERRORS_BY_CODE
)
async def read_client_flows(
    args: ReadClientFlowRequest, authorization: Optional[str] = Header(None)
):
    """Lists out client flows.

    This requires standard authentication with an admin account.
    """
    sort = [srt.to_result() for srt in (args.sort or [])]
    sort = cleanup_sort(CLIENT_FLOW_SORT_OPTIONS, sort, ["uid", "slug"])
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response
        filters_to_apply = flattened_filters(
            dict(
                (k, cast(FilterItemLike, v.to_result()))
                for k, v in args.filters.__dict__.items()
                if v is not None
            )
        )
        items = await raw_read_client_flows(
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
            rev_items = await raw_read_client_flows(itgs, filters_to_apply, rev_sort, 1)
            if rev_items:
                first_item = item_pseudocolumns(items[0])

        if first_item is not None or last_item is not None:
            next_page_sort = get_next_page_sort(first_item, last_item, sort)

        return Response(
            content=ReadClientFlowResponse(
                items=items,
                next_page_sort=(
                    [s.to_model() for s in next_page_sort]
                    if next_page_sort is not None
                    else None
                ),
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )


async def raw_read_client_flows(
    itgs: Itgs,
    filters_to_apply: List[Tuple[str, FilterItemLike]],
    sort: List[SortItem],
    limit: int,
):
    """performs exactly the specified sort without pagination logic"""
    client_flows = Table("client_flows")

    query: QueryBuilder = Query.from_(client_flows).select(
        client_flows.uid,
        client_flows.slug,
        client_flows.name,
        client_flows.description,
        client_flows.client_schema,
        client_flows.server_schema,
        client_flows.replaces,
        client_flows.screens,
        client_flows.rules,
        client_flows.flags,
        client_flows.created_at,
    )
    qargs = []

    def pseudocolumn(key: str) -> Term:
        if key in ("uid", "slug", "name", "description", "flags", "created_at"):
            return client_flows.field(key)
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
    items: List[ClientFlow] = []
    for row in response.results or []:
        items.append(
            ClientFlow(
                uid=row[0],
                slug=row[1],
                name=row[2],
                description=row[3],
                client_schema=json.loads(row[4]),
                server_schema=json.loads(row[5]),
                replaces=bool(row[6]),
                screens=decode_flow_screens(row[7]),
                rules=client_flow_rules_adapter.validate_json(row[8]),
                flags=row[9],
                created_at=row[10],
            )
        )
    return items


def item_pseudocolumns(item: ClientFlow) -> dict:
    """returns the dictified item such that the keys in the return dict match
    the keys of the sort options"""
    return {"uid": item.uid, "slug": item.slug, "created_at": item.created_at}
