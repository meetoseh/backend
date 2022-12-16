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
from resources.standard_text_operator import StandardTextOperator
import image_files.auth as image_files_auth
from image_files.models import ImageFileRef


class JourneyBackgroundImage(BaseModel):
    uid: str = Field(description="The primary stable external identifier for this row")
    image_file: ImageFileRef = Field(description="The underlying image file")
    image_file_created_at: float = Field(
        description=(
            "When the image file was originally uploaded, in seconds since the unix epoch"
        )
    )
    uploaded_by_user_sub: Optional[str] = Field(
        description="The sub of the user who originally uploaded this file, if available"
    )
    last_uploaded_at: float = Field(
        description=(
            "The last time someone uploaded this file in seconds since the unix epoch; "
            "we automatically deduplicate files so this may differ from when the image "
            "file was originally uploaded"
        )
    )


JOURNEY_BACKGROUND_IMAGE_SORT_OPTIONS = [
    SortItem[Literal["uid"], str],
    SortItem[Literal["image_file_created_at"], float],
    SortItem[Literal["last_uploaded_at"], float],
]
JourneyBackgroundImageSortOption = Union[
    SortItemModel[Literal["uid"], str],
    SortItemModel[Literal["image_file_created_at"], float],
    SortItemModel[Literal["last_uploaded_at"], float],
]


class JourneyBackgroundImageFilter(BaseModel):
    uid: Optional[FilterTextItemModel] = Field(
        None, description="the uid of the journey background image"
    )
    image_file_uid: Optional[FilterTextItemModel] = Field(
        None, description="the uid of the image file"
    )
    image_file_created_at: Optional[FilterItemModel[float]] = Field(
        None, description="the timestamp of when the image file was created"
    )
    original_file_sha512: Optional[FilterTextItemModel] = Field(
        None, description="the sha512 of the original file"
    )
    uploaded_by_user_sub: Optional[FilterTextItemModel] = Field(
        None,
        description="the sub of the user who uploaded the image file, if available",
    )
    last_uploaded_at: Optional[FilterItemModel[float]] = Field(
        None, description="the timestamp of when the image file was last uploaded"
    )


class ReadJourneyBackgroundImageRequest(BaseModel):
    filters: JourneyBackgroundImageFilter = Field(
        default_factory=JourneyBackgroundImageFilter, description="the filters to apply"
    )
    sort: Optional[List[JourneyBackgroundImageSortOption]] = Field(
        None, description="the sort order to apply"
    )
    limit: int = Field(
        25, description="the maximum number of results to return", ge=1, le=250
    )


class ReadJourneyBackgroundImageResponse(BaseModel):
    items: List[JourneyBackgroundImage] = Field(
        description="the items matching the results in the given sort"
    )
    next_page_sort: Optional[List[JourneyBackgroundImageSortOption]] = Field(
        description="if there is a next or earlier page, the sort order to use to get it"
    )


router = APIRouter()


@router.post(
    "/search",
    response_model=ReadJourneyBackgroundImageResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_journey_background_images(
    args: ReadJourneyBackgroundImageRequest, authorization: Optional[str] = Header(None)
):
    """Lists out journey background images

    This requires standard authentication for a user with admin access.
    """
    sort = [srt.to_result() for srt in (args.sort or [])]
    sort = cleanup_sort(JOURNEY_BACKGROUND_IMAGE_SORT_OPTIONS, sort, ["uid"])
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
        items = await raw_read_journey_background_images(
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
            rev_items = await raw_read_journey_background_images(
                itgs, filters_to_apply, rev_sort, 1
            )
            if rev_items:
                first_item = item_pseudocolumns(items[0])

        if first_item is not None or last_item is not None:
            next_page_sort = get_next_page_sort(first_item, last_item, sort)

        return Response(
            content=ReadJourneyBackgroundImageResponse(
                items=items,
                next_page_sort=[s.to_model() for s in next_page_sort]
                if next_page_sort is not None
                else None,
            ).json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )


async def raw_read_journey_background_images(
    itgs: Itgs,
    filters_to_apply: List[Tuple[str, Union[FilterItem, FilterTextItem]]],
    sort: List[SortItem],
    limit: int,
):
    """performs exactly the specified sort without pagination logic"""
    journey_background_images = Table("journey_background_images")
    image_files = Table("image_files")
    users = Table("users")

    query: QueryBuilder = (
        Query.from_(journey_background_images)
        .select(
            journey_background_images.uid,
            image_files.uid,
            image_files.created_at,
            users.sub,
            journey_background_images.last_uploaded_at,
        )
        .join(image_files)
        .on(image_files.id == journey_background_images.image_file_id)
        .left_outer_join(users)
        .on(users.id == journey_background_images.uploaded_by_user_id)
    )
    qargs = []

    def pseudocolumn(key: str) -> Term:
        if key == "image_file_created_at":
            return image_files.created_at
        elif key == "image_file_uid":
            return image_files.uid
        elif key == "original_file_sha512":
            return image_files.original_sha512
        elif key == "uploaded_by_user_sub":
            return users.sub
        elif key in ("uid", "last_uploaded_at"):
            return journey_background_images.field(key)
        raise ValueError(f"unknown key: {key}")

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
    items: List[JourneyBackgroundImage] = []
    for row in response.results or []:
        items.append(
            JourneyBackgroundImage(
                uid=row[0],
                image_file=ImageFileRef(
                    uid=row[1], jwt=await image_files_auth.create_jwt(itgs, row[1])
                ),
                image_file_created_at=row[2],
                uploaded_by_user_sub=row[3],
                last_uploaded_at=row[4],
            )
        )
    return items


def item_pseudocolumns(item: JourneyBackgroundImage) -> dict:
    """returns the dictified item such that the keys in the return dict match
    the keys of the sort options"""
    return {
        "uid": item.uid,
        "image_file_uid": item.image_file.uid,
        "image_file_created_at": item.image_file_created_at,
        "uploaded_by_user_sub": item.uploaded_by_user_sub,
        "last_uploaded_at": item.last_uploaded_at,
    }
