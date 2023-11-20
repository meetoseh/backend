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
import content_files.auth as content_files_auth
from content_files.models import ContentFileRef


class JourneyAudioContent(BaseModel):
    uid: str = Field(description="The primary stable external identifier for this row")
    content_file: ContentFileRef = Field(description="The underlying audio file")
    content_file_created_at: float = Field(
        description=(
            "When the content file was originally uploaded, in seconds since the unix epoch"
        )
    )
    uploaded_by_user_sub: Optional[str] = Field(
        description="The sub of the user who originally uploaded this file, if available"
    )
    last_uploaded_at: float = Field(
        description=(
            "The last time someone uploaded this file in seconds since the unix epoch; "
            "we automatically deduplicate files so this may differ from when the content "
            "file was originally uploaded"
        )
    )


JOURNEY_AUDIO_CONTENT_SORT_OPTIONS = [
    SortItem[Literal["uid"], str],
    SortItem[Literal["content_file_created_at"], float],
    SortItem[Literal["last_uploaded_at"], float],
]
JourneyAudioContentSortOption = Union[
    SortItemModel[Literal["uid"], str],
    SortItemModel[Literal["content_file_created_at"], float],
    SortItemModel[Literal["last_uploaded_at"], float],
]


class JourneyAudioContentFilter(BaseModel):
    uid: Optional[FilterTextItemModel] = Field(
        None, description="the uid of the journey audio content"
    )
    content_file_uid: Optional[FilterTextItemModel] = Field(
        None, description="the uid of the content file"
    )
    content_file_created_at: Optional[FilterItemModel[float]] = Field(
        None, description="the timestamp of when the content file was created"
    )
    original_file_sha512: Optional[FilterTextItemModel] = Field(
        None, description="the sha512 of the original file"
    )
    uploaded_by_user_sub: Optional[FilterTextItemModel] = Field(
        None,
        description="the sub of the user who uploaded the content file, if available",
    )
    last_uploaded_at: Optional[FilterItemModel[float]] = Field(
        None, description="the timestamp of when the content file was last uploaded"
    )

    def __init__(
        self,
        *,
        uid: Optional[FilterTextItemModel] = None,
        content_file_uid: Optional[FilterTextItemModel] = None,
        content_file_created_at: Optional[FilterItemModel[float]] = None,
        original_file_sha512: Optional[FilterTextItemModel] = None,
        uploaded_by_user_sub: Optional[FilterTextItemModel] = None,
        last_uploaded_at: Optional[FilterItemModel[float]] = None,
    ):
        super().__init__(
            uid=uid,
            content_file_uid=content_file_uid,
            content_file_created_at=content_file_created_at,
            original_file_sha512=original_file_sha512,
            uploaded_by_user_sub=uploaded_by_user_sub,
            last_uploaded_at=last_uploaded_at,
        )


class ReadJourneyAudioContentRequest(BaseModel):
    filters: JourneyAudioContentFilter = Field(
        default_factory=JourneyAudioContentFilter, description="the filters to apply"
    )
    sort: Optional[List[JourneyAudioContentSortOption]] = Field(
        None, description="the sort order to apply"
    )
    limit: int = Field(
        25, description="the maximum number of results to return", ge=1, le=250
    )


class ReadJourneyAudioContentResponse(BaseModel):
    items: List[JourneyAudioContent] = Field(
        description="the items matching the results in the given sort"
    )
    next_page_sort: Optional[List[JourneyAudioContentSortOption]] = Field(
        description="if there is a next or earlier page, the sort order to use to get it"
    )


router = APIRouter()


@router.post(
    "/search",
    response_model=ReadJourneyAudioContentResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_journey_audio_content(
    args: ReadJourneyAudioContentRequest, authorization: Optional[str] = Header(None)
):
    """Lists out journey audio content

    This requires standard authentication for a user with admin access.
    """
    sort = [srt.to_result() for srt in (args.sort or [])]
    sort = cleanup_sort(JOURNEY_AUDIO_CONTENT_SORT_OPTIONS, sort, ["uid"])
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
        items = await raw_read_journey_audio_content(
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
            rev_items = await raw_read_journey_audio_content(
                itgs, filters_to_apply, rev_sort, 1
            )
            if rev_items:
                first_item = item_pseudocolumns(items[0])

        if first_item is not None or last_item is not None:
            next_page_sort = get_next_page_sort(first_item, last_item, sort)

        return Response(
            content=ReadJourneyAudioContentResponse(
                items=items,
                next_page_sort=[s.to_model() for s in next_page_sort]
                if next_page_sort is not None
                else None,
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )


async def raw_read_journey_audio_content(
    itgs: Itgs,
    filters_to_apply: List[Tuple[str, Union[FilterItem, FilterTextItem]]],
    sort: List[SortItem],
    limit: int,
):
    """performs exactly the specified sort without pagination logic"""
    journey_audio_contents = Table("journey_audio_contents")
    content_files = Table("content_files")
    users = Table("users")

    query: QueryBuilder = (
        Query.from_(journey_audio_contents)
        .select(
            journey_audio_contents.uid,
            content_files.uid,
            content_files.created_at,
            users.sub,
            journey_audio_contents.last_uploaded_at,
        )
        .join(content_files)
        .on(content_files.id == journey_audio_contents.content_file_id)
        .left_outer_join(users)
        .on(users.id == journey_audio_contents.uploaded_by_user_id)
    )
    qargs = []

    def pseudocolumn(key: str) -> Term:
        if key == "content_file_created_at":
            return content_files.created_at
        elif key == "content_file_uid":
            return content_files.uid
        elif key == "original_file_sha512":
            return content_files.original_sha512
        elif key == "uploaded_by_user_sub":
            return users.sub
        elif key in ("uid", "last_uploaded_at"):
            return journey_audio_contents.field(key)
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
    items: List[JourneyAudioContent] = []
    for row in response.results or []:
        items.append(
            JourneyAudioContent(
                uid=row[0],
                content_file=ContentFileRef(
                    uid=row[1], jwt=await content_files_auth.create_jwt(itgs, row[1])
                ),
                content_file_created_at=row[2],
                uploaded_by_user_sub=row[3],
                last_uploaded_at=row[4],
            )
        )
    return items


def item_pseudocolumns(item: JourneyAudioContent) -> dict:
    """returns the dictified item such that the keys in the return dict match
    the keys of the sort options"""
    return {
        "uid": item.uid,
        "content_file_uid": item.content_file.uid,
        "content_file_created_at": item.content_file_created_at,
        "uploaded_by_user_sub": item.uploaded_by_user_sub,
        "last_uploaded_at": item.last_uploaded_at,
    }
