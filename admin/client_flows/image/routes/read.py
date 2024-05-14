from pypika import Table, Query, Parameter
from pypika.queries import QueryBuilder
from pypika.terms import Term
from typing import Annotated, Any, Dict, List, Literal, Optional, Tuple, Union, cast
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
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


class ClientFlowImage(BaseModel):
    uid: str = Field(description="The primary stable external identifier for this row")
    list_slug: str = Field(description="The slug of the list this image belongs to")
    image_file: ImageFileRef = Field(description="The underlying image file")
    original_file_sha512: str = Field(
        description="The sha512 of the file that was uploaded"
    )
    image_file_created_at: float = Field(
        description="When the image file was originally uploaded, in seconds since the epoch"
    )
    last_uploaded_at: float = Field(
        description="the last time this file was uploaded, in seconds since the epoch"
    )


CLIENT_FLOW_IMAGE_SORT_OPTIONS = [
    SortItem[Literal["uid"], str],
    SortItem[Literal["list_slug"], str],
    SortItem[Literal["image_file_created_at"], float],
    SortItem[Literal["last_uploaded_at"], float],
]
ClientFlowImageSortOption = Union[
    SortItemModel[Literal["uid"], str],
    SortItemModel[Literal["list_slug"], str],
    SortItemModel[Literal["image_file_created_at"], float],
    SortItemModel[Literal["last_uploaded_at"], float],
]


class ClientFlowImageFilter(BaseModel):
    uid: Optional[FilterTextItemModel] = Field(
        None, description="primary stable row identifier"
    )
    list_slug: Optional[FilterTextItemModel] = Field(
        None, description="the slug of the list this image belongs to"
    )
    image_file_uid: Optional[FilterTextItemModel] = Field(
        None, description="the uid of the original image file"
    )
    original_file_sha512: Optional[FilterTextItemModel] = Field(
        None, description="the sha512 of the original image that was processed"
    )
    image_original_file_sha512: Optional[FilterTextItemModel] = Field(
        None,
        description=(
            "the sha512 of the image after preprocessing. For example, if the processor accepts "
            "a JSON file which it uses to create an image which then goes through the standard "
            "cropping/resizing algorithm, then the `original_file_sha512` is the sha512 of the JSON "
            "file uploaded, whereas `image_original_sha512` is the sha512 of the image it generated "
            "from that json file and became the original_sha512 on the `image_files` record"
        ),
    )
    last_uploaded_at: Optional[FilterItemModel[float]] = Field(
        None, description="the last time the file was uploaded"
    )


class ReadClientFlowImageRequest(BaseModel):
    filters: ClientFlowImageFilter = Field(
        default_factory=lambda: ClientFlowImageFilter.model_validate({}),
        description="the filters to apply",
    )
    sort: Optional[List[ClientFlowImageSortOption]] = Field(
        None, description="the sort order to apply"
    )
    limit: int = Field(
        25, description="the maximum number of rows to return", ge=1, le=250
    )


class ReadClientFlowImageResponse(BaseModel):
    items: List[ClientFlowImage] = Field(
        description="the items matching the filters in the given sort"
    )
    next_page_sort: Optional[List[ClientFlowImageSortOption]] = Field(
        None, description="if there is a next or earlier page, the sort order to get it"
    )


router = APIRouter()


@router.post(
    "/search",
    response_model=ReadClientFlowImageResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_client_flow_images(
    args: ReadClientFlowImageRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Lists out client flow images

    This requires standard authorization for a user with admin access
    """
    sort = [srt.to_result() for srt in (args.sort or [])]
    sort = cleanup_sort(CLIENT_FLOW_IMAGE_SORT_OPTIONS, sort, ["uid"])
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
        items = await raw_read_client_flow_images(
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
            rev_items = await raw_read_client_flow_images(
                itgs, filters_to_apply, rev_sort, 1
            )
            if rev_items:
                first_item = item_pseudocolumns(items[0])

        if first_item is not None or last_item is not None:
            next_page_sort = get_next_page_sort(first_item, last_item, sort)

        return Response(
            content=ReadClientFlowImageResponse.__pydantic_serializer__.to_json(
                ReadClientFlowImageResponse(
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


async def raw_read_client_flow_images(
    itgs: Itgs,
    filters_to_apply: List[Tuple[str, FilterItemLike]],
    sort: List[SortItem],
    limit: int,
) -> List[ClientFlowImage]:
    """performs exactly the specified sort without pagination logic"""
    client_flow_images = Table("client_flow_images")
    image_files = Table("image_files")

    query: QueryBuilder = (
        Query.from_(client_flow_images)
        .select(
            client_flow_images.uid,
            client_flow_images.list_slug,
            image_files.uid,
            client_flow_images.original_sha512,
            image_files.created_at,
            client_flow_images.last_uploaded_at,
        )
        .join(image_files)
        .on(image_files.id == client_flow_images.image_file_id)
    )
    qargs = []

    def pseudocolumn(key: str) -> Term:
        if key in ("uid", "list_slug", "last_uploaded_at"):
            return client_flow_images.field(key)
        elif key == "image_file_uid":
            return image_files.field("uid")
        elif key == "image_file_created_at":
            return image_files.field("created_at")
        elif key == "original_file_sha512":
            return client_flow_images.field("original_sha512")
        elif key == "image_original_file_sha512":
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
    items: List[ClientFlowImage] = []
    for row in response.results or []:
        items.append(
            ClientFlowImage(
                uid=row[0],
                list_slug=row[1],
                image_file=ImageFileRef(
                    uid=row[2], jwt=await image_files_auth.create_jwt(itgs, row[2])
                ),
                original_file_sha512=row[3],
                image_file_created_at=row[4],
                last_uploaded_at=row[5],
            )
        )
    return items


def item_pseudocolumns(item: ClientFlowImage) -> dict:
    """returns the dictified item such that the keys in the return dict match
    the keys of the sort options"""
    return {
        "uid": item.uid,
        "list_slug": item.list_slug,
        "image_file_created_at": item.image_file_created_at,
        "last_uploaded_at": item.last_uploaded_at,
    }
