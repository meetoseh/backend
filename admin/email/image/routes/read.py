from pypika import Table, Query, Parameter
from pypika.queries import QueryBuilder
from pypika.terms import Term
from typing import Annotated, Any, Dict, List, Literal, Optional, Tuple, Union, cast
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from admin.email.image.routes.create import Size
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE
from resources.filter import sort_criterion, flattened_filters
from resources.filter_item import FilterItemModel
from resources.filter_item_like import FilterItemLike
from resources.sort import cleanup_sort, get_next_page_sort, reverse_sort
from resources.sort_item import SortItem, SortItemModel
from resources.filter_text_item import FilterTextItemModel
from itgs import Itgs
import image_files.auth as image_files_auth
from image_files.models import ImageFileRef


class EmailImage(BaseModel):
    uid: str = Field(description="The primary stable external identifier for this row")
    image_file: ImageFileRef = Field(description="The underlying image file")
    size: Size = Field(
        description="The size that is embedded into the html where this image is used"
    )
    original_file_sha512: str = Field(
        description="The sha512 of the file that was uploaded"
    )
    created_at: float = Field(description="When the record in email_images was created")


EMAIL_IMAGE_SORT_OPTIONS = [
    SortItem[Literal["uid"], str],
    SortItem[Literal["created_at"], float],
]
EmailImageSortOption = Union[
    SortItemModel[Literal["uid"], str],
    SortItemModel[Literal["created_at"], float],
]


class EmailImageFilter(BaseModel):
    uid: Optional[FilterTextItemModel] = Field(
        None, description="primary stable row identifier"
    )
    image_file_uid: Optional[FilterTextItemModel] = Field(
        None, description="the uid of the original image file"
    )
    width: Optional[FilterItemModel[int]] = Field(
        None, description="the width of the image"
    )
    height: Optional[FilterItemModel[int]] = Field(
        None, description="the height of the image"
    )
    original_file_sha512: Optional[FilterTextItemModel] = Field(
        None, description="the sha512 of the original image that was processed"
    )
    created_at: Optional[FilterItemModel[float]] = Field(
        None, description="when this record was created"
    )


class ReadEmailImageRequest(BaseModel):
    filters: EmailImageFilter = Field(
        default_factory=lambda: EmailImageFilter.model_validate({}),
        description="the filters to apply",
    )
    sort: Optional[List[EmailImageSortOption]] = Field(
        None, description="the sort order to apply"
    )
    limit: int = Field(
        25, description="the maximum number of rows to return", ge=1, le=250
    )


class ReadEmailImageResponse(BaseModel):
    items: List[EmailImage] = Field(
        description="the items matching the filters in the given sort"
    )
    next_page_sort: Optional[List[EmailImageSortOption]] = Field(
        None, description="if there is a next or earlier page, the sort order to get it"
    )


router = APIRouter()


@router.post(
    "/search",
    response_model=ReadEmailImageResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_email_images(
    args: ReadEmailImageRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Lists out email images. Unlike many image listings, the images themselves
    are not guarranteed to be unique as it may be helpful to have different
    links to the same image to reduce the pain if one of them needs to be
    deleted due to hotlinking.

    This requires standard authorization for a user with admin access
    """
    sort = [srt.to_result() for srt in (args.sort or [])]
    sort = cleanup_sort(EMAIL_IMAGE_SORT_OPTIONS, sort, ["uid"])
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
        items = await raw_read_email_images(
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
            rev_items = await raw_read_email_images(itgs, filters_to_apply, rev_sort, 1)
            if rev_items:
                first_item = item_pseudocolumns(items[0])

        if first_item is not None or last_item is not None:
            next_page_sort = get_next_page_sort(first_item, last_item, sort)

        return Response(
            content=ReadEmailImageResponse.__pydantic_serializer__.to_json(
                ReadEmailImageResponse(
                    items=items,
                    next_page_sort=(
                        [s.to_model() for s in next_page_sort]
                        if next_page_sort is not None
                        else None
                    ),
                )
            ),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )


async def raw_read_email_images(
    itgs: Itgs,
    filters_to_apply: List[Tuple[str, FilterItemLike]],
    sort: List[SortItem],
    limit: int,
) -> List[EmailImage]:
    """performs exactly the specified sort without pagination logic"""
    email_images = Table("email_images")
    image_files = Table("image_files")

    query: QueryBuilder = (
        Query.from_(email_images)
        .select(
            email_images.uid,
            image_files.uid,
            email_images.width,
            email_images.height,
            image_files.original_sha512,
            email_images.created_at,
        )
        .join(image_files)
        .on(image_files.id == email_images.image_file_id)
    )
    qargs = []

    def pseudocolumn(key: str) -> Term:
        if key in ("uid", "width", "height", "created_at"):
            return email_images.field(key)
        elif key == "image_file_uid":
            return image_files.field("uid")
        elif key == "original_file_sha512":
            return image_files.field("original_sha512")
        raise ValueError(f"Unknown pseudocolumn {key}")

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
    items: List[EmailImage] = []
    for row in response.results or []:
        items.append(
            EmailImage(
                uid=row[0],
                image_file=ImageFileRef(
                    uid=row[1], jwt=await image_files_auth.create_jwt(itgs, row[1])
                ),
                size=Size(width=row[2], height=row[3]),
                original_file_sha512=row[4],
                created_at=row[5],
            )
        )
    return items


def item_pseudocolumns(item: EmailImage) -> dict:
    """returns the dictified item such that the keys in the return dict match
    the keys of the sort options"""
    return {"uid": item.uid, "created_at": item.created_at}
