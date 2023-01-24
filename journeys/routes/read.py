import json
from pypika import Table, Query, Parameter
from pypika.queries import QueryBuilder
from pypika.terms import Term, Function, ExistsCriterion
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
from content_files.models import ContentFileRef
import content_files.auth as content_files_auth
from image_files.models import ImageFileRef
import image_files.auth as image_files_auth
from instructors.routes.read import Instructor
from journeys.subcategories.routes.read import JourneySubcategory
from journeys.routes.create import Prompt


class Journey(BaseModel):
    uid: str = Field(
        description="The primary stable external identifier for the new journey"
    )
    audio_content: ContentFileRef = Field(
        description="The content file containing the audio of the journey"
    )
    background_image: ImageFileRef = Field(
        description="The image file for the background of the journey"
    )
    blurred_background_image: ImageFileRef = Field(
        description="The blurred version of the background image"
    )
    subcategory: JourneySubcategory = Field(
        description="The subcategory this journey belongs to"
    )
    instructor: Instructor = Field(
        description="The instructor we are crediting for this journey"
    )
    title: str = Field(description="The display title")
    description: str = Field(description="The display description")
    prompt: Prompt = Field(
        description="The prompt style, text, and options to display to the user"
    )
    created_at: float = Field(
        description="The timestamp of when this journey was created"
    )
    deleted_at: Optional[float] = Field(
        description="The timestamp of when this journey was soft-deleted"
    )
    daily_event_uid: Optional[str] = Field(
        description="If the journey is assigned to a daily event, the uid of that event"
    )


JOURNEY_SORT_OPTIONS = [
    SortItem[Literal["uid"], str],
    SortItem[Literal["title"], str],
    SortItem[Literal["created_at"], float],
    SortItem[Literal["deleted_at"], float],
]
JourneySortOption = Union[
    SortItemModel[Literal["uid"], str],
    SortItemModel[Literal["title"], str],
    SortItemModel[Literal["created_at"], float],
    SortItemModel[Literal["deleted_at"], float],
]


class JourneyFilter(BaseModel):
    uid: Optional[FilterTextItemModel] = Field(
        None, description="the uid of the journey"
    )
    audio_content_file_uid: Optional[FilterTextItemModel] = Field(
        None, description="the uid of the audio content file"
    )
    background_image_file_uid: Optional[FilterTextItemModel] = Field(
        None, description="the uid of the background image file"
    )
    blurred_background_image_file_uid: Optional[FilterTextItemModel] = Field(
        None, description="the uid of the blurred background image file"
    )
    subcategory_uid: Optional[FilterTextItemModel] = Field(
        None, description="the uid of the subcategory"
    )
    subcategory_internal_name: Optional[FilterTextItemModel] = Field(
        None, description="the internal name of the subcategory"
    )
    subcategory_external_name: Optional[FilterTextItemModel] = Field(
        None, description="the external name of the subcategory"
    )
    instructor_uid: Optional[FilterTextItemModel] = Field(
        None, description="the uid of the instructor"
    )
    title: Optional[FilterTextItemModel] = Field(
        None, description="the title of the journey"
    )
    description: Optional[FilterTextItemModel] = Field(
        None, description="the description of the journey"
    )
    prompt_style: Optional[FilterTextItemModel] = Field(
        None, description="the prompt style of the journey"
    )
    created_at: Optional[FilterItemModel[float]] = Field(
        None, description="when the journey was created in seconds since the unix epoch"
    )
    deleted_at: Optional[FilterItemModel[Optional[float]]] = Field(
        None, description="when the journey was deleted in seconds since the unix epoch"
    )
    daily_event_uid: Optional[FilterItemModel[Optional[str]]] = Field(
        None, description="the uid of the daily event the journey belongs to"
    )


class ReadJourneyRequest(BaseModel):
    filters: JourneyFilter = Field(
        default_factory=JourneyFilter, description="the filters to apply"
    )
    sort: Optional[List[JourneySortOption]] = Field(
        None, description="the sort order to apply"
    )
    limit: int = Field(
        15, description="the maximum number of results to return", ge=1, le=150
    )


class ReadJourneyResponse(BaseModel):
    items: List[Journey] = Field(
        description="the items matching the request in the given sort"
    )
    next_page_sort: Optional[List[JourneySortOption]] = Field(
        None,
        description="if there is a next/previous page, the sort order to use to get the next page",
    )


router = APIRouter()


@router.post(
    "/search", response_model=ReadJourneyResponse, responses=STANDARD_ERRORS_BY_CODE
)
async def read_journeys(
    args: ReadJourneyRequest, authorization: Optional[str] = Header(None)
):
    """lists out journeys

    This requires standard authorization for an admin user
    """
    sort = [srt.to_result() for srt in (args.sort or [])]
    sort = cleanup_sort(JOURNEY_SORT_OPTIONS, sort, ["uid"])
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
        items = await raw_read_journeys(itgs, filters_to_apply, sort, args.limit + 1)
        next_page_sort: Optional[List[SortItem]] = None
        last_item: Optional[Dict[str, Any]] = None
        if len(items) > args.limit:
            items = items[: args.limit]
            last_item = item_pseudocolumns(items[-1])
        first_item: Optional[Dict[str, Any]] = None
        if items and any(s.after is not None for s in sort):
            rev_sort = reverse_sort(sort, "make_exclusive")
            rev_items = await raw_read_journeys(itgs, filters_to_apply, rev_sort, 1)
            if rev_items:
                first_item = item_pseudocolumns(items[0])

        if first_item is not None or last_item is not None:
            next_page_sort = get_next_page_sort(first_item, last_item, sort)

        return Response(
            content=ReadJourneyResponse(
                items=items,
                next_page_sort=[s.to_model() for s in next_page_sort]
                if next_page_sort is not None
                else None,
            ).json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )


async def raw_read_journeys(
    itgs: Itgs,
    filters_to_apply: List[Tuple[str, Union[FilterItem, FilterTextItem]]],
    sort: List[SortItem],
    limit: int,
):
    """performs exactly the specified sort without pagination logic"""
    journeys = Table("journeys")
    content_files = Table("content_files")
    image_files = Table("image_files")
    blurred_image_files = image_files.as_("blurred_image_files")
    journey_subcategories = Table("journey_subcategories")
    instructors = Table("instructors")
    instructor_pictures = image_files.as_("instructor_pictures")
    daily_event_journeys = Table("daily_event_journeys")
    daily_events = Table("daily_events")

    query: QueryBuilder = (
        Query.from_(journeys)
        .select(
            journeys.uid,
            content_files.uid,
            image_files.uid,
            journey_subcategories.uid,
            journey_subcategories.internal_name,
            journey_subcategories.external_name,
            instructors.uid,
            instructors.name,
            instructor_pictures.uid,
            instructors.created_at,
            instructors.deleted_at,
            journeys.title,
            journeys.description,
            journeys.prompt,
            journeys.created_at,
            journeys.deleted_at,
            daily_events.uid,
            blurred_image_files.uid,
        )
        .join(content_files)
        .on(content_files.id == journeys.audio_content_file_id)
        .join(image_files)
        .on(image_files.id == journeys.background_image_file_id)
        .join(blurred_image_files)
        .on(blurred_image_files.id == journeys.blurred_background_image_file_id)
        .join(journey_subcategories)
        .on(journey_subcategories.id == journeys.journey_subcategory_id)
        .join(instructors)
        .on(instructors.id == journeys.instructor_id)
        .left_outer_join(instructor_pictures)
        .on(instructor_pictures.id == instructors.picture_image_file_id)
        .left_outer_join(daily_events)
        .on(
            ExistsCriterion(
                Query.from_(daily_event_journeys)
                .select(1)
                .where(daily_event_journeys.journey_id == journeys.id)
                .where(daily_event_journeys.daily_event_id == daily_events.id)
            )
        )
    )
    qargs = []

    def pseudocolumn(key: str) -> Term:
        if key in ("uid", "title", "description", "created_at", "deleted_at"):
            return journeys.field(key)
        elif key == "audio_content_file_uid":
            return content_files.uid
        elif key == "background_image_file_uid":
            return image_files.uid
        elif key == "subcategory_uid":
            return journey_subcategories.uid
        elif key == "subcategory_internal_name":
            return journey_subcategories.internal_name
        elif key == "subcategory_external_name":
            return journey_subcategories.external_name
        elif key == "instructor_uid":
            return instructors.uid
        elif key == "prompt_style":
            return Function("json_extract", journeys.prompt, "style")
        elif key == "daily_event_uid":
            return daily_events.uid
        elif key == "blurred_background_image_file_uid":
            return blurred_image_files.uid
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
    items: List[Journey] = []
    for row in response.results or []:
        items.append(
            Journey(
                uid=row[0],
                audio_content=ContentFileRef(
                    uid=row[1], jwt=await content_files_auth.create_jwt(itgs, row[1])
                ),
                background_image=ImageFileRef(
                    uid=row[2], jwt=await image_files_auth.create_jwt(itgs, row[2])
                ),
                subcategory=JourneySubcategory(
                    uid=row[3], internal_name=row[4], external_name=row[5]
                ),
                instructor=Instructor(
                    uid=row[6],
                    name=row[7],
                    picture=(
                        ImageFileRef(
                            uid=row[8],
                            jwt=await image_files_auth.create_jwt(itgs, row[8]),
                        )
                        if row[8] is not None
                        else None
                    ),
                    created_at=row[9],
                    deleted_at=row[10],
                ),
                title=row[11],
                description=row[12],
                prompt=json.loads(row[13]),
                created_at=row[14],
                deleted_at=row[15],
                daily_event_uid=row[16],
                blurred_background_image=ImageFileRef(
                    uid=row[17], jwt=await image_files_auth.create_jwt(itgs, row[17])
                ),
            )
        )
    return items


def item_pseudocolumns(item: Journey) -> dict:
    """returns the dictified item such that the keys in the return dict match
    the keys of the sort options"""
    return {
        "uid": item.uid,
        "title": item.title,
        "created_at": item.created_at,
        "deleted_at": item.deleted_at,
        "audio_content_file_uid": item.audio_content.uid,
        "background_image_file_uid": item.background_image.uid,
        "blurred_background_image_file_uid": item.blurred_background_image.uid,
        "subcategory_uid": item.subcategory.uid,
        "subcategory_internal_name": item.subcategory.internal_name,
        "subcategory_external_name": item.subcategory.external_name,
        "instructor_uid": item.instructor.uid,
        "description": item.description,
        "prompt_style": item.prompt.style,
    }
