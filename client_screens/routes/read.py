import json
from pypika import Table, Query, Parameter
from pypika.queries import QueryBuilder
from pypika.terms import Term
from typing import Any, Dict, List, Literal, Optional, Tuple, Union, cast
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE
from resources.filter import sort_criterion, flattened_filters
from resources.filter_bit_field_item import FilterBitFieldItemModel
from resources.filter_item_like import FilterItemLike
from resources.sort import cleanup_sort, get_next_page_sort, reverse_sort
from resources.sort_item import SortItem, SortItemModel
from resources.filter_text_item import FilterTextItemModel
from itgs import Itgs


class ClientScreen(BaseModel):
    uid: str = Field(description="Primary stable external row identifier")
    slug: str = Field(description="Semantic identifier for the client screen")
    name: str = Field(description="Human readable name for the client screen")
    description: str = Field(
        description="Human readable description for the client screen"
    )
    screen_schema: dict = Field(
        description=(
            "Openapi 3.0.3 schema object, but with all refs (including internal refs) forbidden:\n"
            "https://spec.openapis.org/oas/v3.0.3#schema-object\n\n"
            "Includes additional format options and specification extensions:\n"
            "https://datatracker.ietf.org/doc/html/draft-wright-json-schema-validation-00#section-7"
            "https://spec.openapis.org/oas/v3.0.3#specification-extensions\n\n"
            '- `{"type": "string", "format": "image_uid"}`: Indicates that the\n'
            "  screen input parameter will be converted to an object of the form\n"
            '  `{"uid": "string", "jwt": "string", "thumbhash": "string"}`\n'
            "  before being passed to the client, where `uid` is the provided string and\n"
            "  jwt provides access to the image file with that uid, and thumbhash provides\n"
            "  a thumbhash of the image at an arbitrary common resolution. Has extension properties:\n"
            '  - `x-processor` - `{"job": "string", "list": "string"}`: A hint for how\n'
            "    file uploads should be processed to generate valid images for this field\n"
            '  - `x-thumbhash`: `{"width": int, "height": int}`: A hint for which image file\n'
            "    export is chosen for the inline thumbhash\n"
            '- `{"type": "string", "format": "content_uid"}`: Indicates that the\n'
            "  screen input parameter will be converted to an object of the form\n"
            "  ```json\n"
            "  {\n"
            '    "content": { "uid": "string", "jwt": "string" },\n'
            '    "transcript": { "uid": "string", "jwt": "string" }\n'
            "  }\n"
            "  ```\n"
            "  before being passed to the client, where content[uid] is the provided string and\n"
            "  the jwt provides access to the content file with that uid. If that content file has\n"
            "  a transcript available, then transcript is a ref to that transcript, otherwise it\n"
            "  will be null. Has extension properties:\n"
            '  - `x-processor` - `{"job": "string", "list": "string"}`: A hint for how\n'
            "    file uploads should be processed to generate valid content for this field\n"
            '- `{"type": "string", "format": "journey_uid"}`: Indicates that the screen input\n'
            "  parameter will be converted to an object of the form\n"
            '  `{"uid": "string", "jwt": "string"}`\n'
            "  before being passed to the client, where `uid` is the provided string and\n"
            "  jwt provides access to the journey with that uid.\n"
            '- `{"type": "string", "format": "course_uid"}`: Indicates that the screen input\n'
            "  parameter will be converted to an object of the form\n"
            '  `{"uid": "string", jwt": "string"}`\n'
            "  before being passed to the client, where `uid` is the provided string and\n"
            "  jwt provides access to the course with that uid.\n"
            '- `{"type": "string", "format": "flow_slug"}`: Indicates that the screen input\n'
            "  parameter will be copied over and used as the trigger at the end of this screen.\n"
            "  Doesn't require trusted input (as its just copied to the client), thus is just a hint\n"
            "  to the admin area for what type of form element to use.\n"
            "\n"
            "Unless otherwise specified, custom formats cannot be targeted by any variable client "
            "flow input which uses either standard parameters or client flow parameters, to prevent "
            "untrusted input from being used within a JWT claim."
        ),
    )
    flags: int = Field(
        description="64-bit signed integer, where each bit represents a boolean flag, which, from lowest to highest:\n"
        "- `1 << 0`: shows in admin: by default, the admin client filters to those with this bit set\n"
        "- `1 << 1`: shows on browser: if not set, skipped for browser clients\n"
        "- `1 << 2`: shows on ios: if not set, skipped for iOS clients\n"
        "- `1 << 3`: shows on android: if not set, skipped for Android clients\n"
    )


CLIENT_SCREEN_SORT_OPTIONS = [
    SortItem[Literal["uid"], str],
    SortItem[Literal["slug"], str],
    SortItem[Literal["name"], str],
]
ClientScreenSortOption = Union[
    SortItemModel[Literal["uid"], str],
    SortItemModel[Literal["slug"], str],
    SortItemModel[Literal["name"], str],
]


class ClientScreenFilter(BaseModel):
    uid: Optional[FilterTextItemModel] = Field(
        None, description="the primary stable identifier"
    )
    slug: Optional[FilterTextItemModel] = Field(None, description="the semantic slug")
    name: Optional[FilterTextItemModel] = Field(
        None, description="the human readable name"
    )
    flags: Optional[FilterBitFieldItemModel] = Field(None, description="the flags")


class ReadClientScreenRequest(BaseModel):
    filters: ClientScreenFilter = Field(
        default_factory=lambda: ClientScreenFilter.model_validate({}),
        description="the filters to apply",
    )
    sort: Optional[List[ClientScreenSortOption]] = Field(
        None, description="the order to sort by"
    )
    limit: int = Field(
        100, description="the maximum number of rows to return", ge=1, le=1000
    )


class ReadClientScreenResponse(BaseModel):
    items: List[ClientScreen] = Field(
        description="the items matching the filters in the given sort"
    )
    next_page_sort: Optional[List[ClientScreenSortOption]] = Field(
        description=(
            "if there is a next page or an earlier page, provides the necessary "
            "sort criteria to get it"
        )
    )


router = APIRouter()


@router.post(
    "/search",
    response_model=ReadClientScreenResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_client_screens(
    args: ReadClientScreenRequest, authorization: Optional[str] = Header(None)
):
    """Lists out client screens.

    This requires standard authentication with an admin account.
    """
    sort = [srt.to_result() for srt in (args.sort or [])]
    sort = cleanup_sort(CLIENT_SCREEN_SORT_OPTIONS, sort, ["slug", "uid"])
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
        items = await raw_read_client_screens(
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
            rev_items = await raw_read_client_screens(
                itgs, filters_to_apply, rev_sort, 1
            )
            if rev_items:
                first_item = item_pseudocolumns(items[0])

        if first_item is not None or last_item is not None:
            next_page_sort = get_next_page_sort(first_item, last_item, sort)

        return Response(
            content=ReadClientScreenResponse(
                items=items,
                next_page_sort=(
                    [s.to_model() for s in next_page_sort]
                    if next_page_sort is not None
                    else None
                ),
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )


async def raw_read_client_screens(
    itgs: Itgs,
    filters_to_apply: List[Tuple[str, FilterItemLike]],
    sort: List[SortItem],
    limit: int,
):
    """performs exactly the specified sort without pagination logic"""
    client_screens = Table("client_screens")

    query: QueryBuilder = Query.from_(client_screens).select(
        client_screens.uid,
        client_screens.slug,
        client_screens.name,
        client_screens.description,
        client_screens.schema,
        client_screens.flags,
    )
    qargs = []

    def pseudocolumn(key: str) -> Term:
        if key in ("uid", "slug", "name", "description", "flags"):
            return client_screens.field(key)
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
    items: List[ClientScreen] = []
    for row in response.results or []:
        items.append(
            ClientScreen(
                uid=row[0],
                slug=row[1],
                name=row[2],
                description=row[3],
                screen_schema=json.loads(row[4]),
                flags=row[5],
            )
        )
    return items


def item_pseudocolumns(item: ClientScreen) -> dict:
    """returns the dictified item such that the keys in the return dict match
    the keys of the sort options"""
    return {"uid": item.uid, "slug": item.slug, "name": item.name}
