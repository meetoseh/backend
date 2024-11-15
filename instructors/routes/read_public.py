from pypika import Table, Query, Parameter
from pypika.queries import QueryBuilder
from pypika.terms import Term, BitwiseAndCriterion
from typing import Any, Dict, List, Literal, Optional, Tuple, Union, cast
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from auth import auth_any
from instructors.lib.instructor_flags import InstructorFlags
from models import STANDARD_ERRORS_BY_CODE
from resources.filter import sort_criterion, flattened_filters
from resources.filter_item_like import FilterItemLike
from resources.sort import cleanup_sort, get_next_page_sort, reverse_sort
from resources.sort_item import SortItem, SortItemModel
from resources.filter_text_item import FilterTextItemModel
from image_files.models import ImageFileRef
import image_files.auth as img_file_auth
from itgs import Itgs


class Instructor(BaseModel):
    uid: str = Field(
        description="The primary stable external identifier for this instructor"
    )
    name: str = Field(description="The display name for this instructor")
    picture: Optional[ImageFileRef] = Field(
        description="The profile picture for this instructor"
    )


INSTRUCTOR_SORT_OPTIONS = [
    SortItem[Literal["uid"], str],
    SortItem[Literal["name"], str],
]
InstructorSortOption = Union[
    SortItemModel[Literal["uid"], str],
    SortItemModel[Literal["name"], str],
]


class InstructorFilter(BaseModel):
    uid: Optional[FilterTextItemModel] = Field(
        None, description="the uid of the instructor"
    )
    name: Optional[FilterTextItemModel] = Field(
        None, description="the name of the instructor"
    )


class ReadInstructorRequest(BaseModel):
    filters: InstructorFilter = Field(
        default_factory=lambda: InstructorFilter.model_validate({}),
        description="the filters to apply",
    )
    sort: Optional[List[InstructorSortOption]] = Field(
        None, description="the order to sort by"
    )
    limit: int = Field(
        25, description="the maximum number of instructors to return", ge=1, le=250
    )


class ReadInstructorResponse(BaseModel):
    items: List[Instructor] = Field(
        description="the items matching the filters in the given sort"
    )
    next_page_sort: Optional[List[InstructorSortOption]] = Field(
        description=(
            "if there is a next page or an earlier page, provides the necessary "
            "sort criteria to get it"
        )
    )


router = APIRouter()


@router.post(
    "/search_public",
    response_model=ReadInstructorResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_public_instructors(
    args: ReadInstructorRequest, authorization: Optional[str] = Header(None)
):
    """Lists out instructors that show in the Classes filter.

    This requires standard authentication.
    """
    sort = [srt.to_result() for srt in (args.sort or [])]
    sort = cleanup_sort(INSTRUCTOR_SORT_OPTIONS, sort, ["uid"])
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response
        filters_to_apply = flattened_filters(
            dict(
                (k, cast(FilterItemLike, v.to_result()))
                for k, v in args.filters.__dict__.items()
                if v is not None
            )
        )
        items = await raw_read_instructors(itgs, filters_to_apply, sort, args.limit + 1)
        next_page_sort: Optional[List[SortItem]] = None
        last_item: Optional[Dict[str, Any]] = None
        if len(items) > args.limit:
            items = items[: args.limit]
            last_item = item_pseudocolumns(items[-1])
        first_item: Optional[Dict[str, Any]] = None
        if items and any(s.after is not None for s in sort):
            rev_sort = reverse_sort(sort, "make_exclusive")
            rev_items = await raw_read_instructors(itgs, filters_to_apply, rev_sort, 1)
            if rev_items:
                first_item = item_pseudocolumns(items[0])

        if first_item is not None or last_item is not None:
            next_page_sort = get_next_page_sort(first_item, last_item, sort)

        return Response(
            content=ReadInstructorResponse(
                items=items,
                next_page_sort=(
                    [s.to_model() for s in next_page_sort]
                    if next_page_sort is not None
                    else None
                ),
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )


async def raw_read_instructors(
    itgs: Itgs,
    filters_to_apply: List[Tuple[str, FilterItemLike]],
    sort: List[SortItem],
    limit: int,
):
    """performs exactly the specified sort without pagination logic"""
    instructors = Table("instructors")
    image_files = Table("image_files")

    query: QueryBuilder = (
        Query.from_(instructors)
        .select(
            instructors.uid,
            instructors.name,
            image_files.uid,
        )
        .left_outer_join(image_files)
        .on(image_files.id == instructors.picture_image_file_id)
        .where(
            BitwiseAndCriterion(
                instructors.field("flags"),
                Term.wrap_constant(int(InstructorFlags.SHOWS_IN_CLASSES_FILTER)),
            )
            == Term.wrap_constant(int(InstructorFlags.SHOWS_IN_CLASSES_FILTER))
        )
    )
    qargs = []

    def pseudocolumn(key: str) -> Term:
        if key in ("uid", "name"):
            return instructors.field(key)
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
    items: List[Instructor] = []
    for row in response.results or []:
        image_file_uid = cast(Optional[str], row[2])
        image_file_ref: Optional[ImageFileRef] = None
        if image_file_uid is not None:
            image_file_jwt = await img_file_auth.create_jwt(itgs, image_file_uid)
            image_file_ref = ImageFileRef(uid=image_file_uid, jwt=image_file_jwt)

        items.append(
            Instructor(
                uid=row[0],
                name=row[1],
                picture=image_file_ref,
            )
        )
    return items


def item_pseudocolumns(item: Instructor) -> dict:
    """returns the dictified item such that the keys in the return dict match
    the keys of the sort options"""
    return {"uid": item.uid, "name": item.name}
