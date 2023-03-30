import json
from pypika import Table, Query, Parameter
from pypika.queries import QueryBuilder
from pypika.terms import Term, Function, ExistsCriterion
from typing import Any, Dict, List, Literal, Optional, Tuple, Union
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from auth import auth_admin
from content_files.models import ContentFileRef
import content_files.auth as content_files_auth
from image_files.models import ImageFileRef
import image_files.auth as image_files_auth
from instructors.routes.read import Instructor
from journeys.routes.read import Journey
from journeys.subcategories.routes.read import JourneySubcategory
from models import STANDARD_ERRORS_BY_CODE
from resources.filter import sort_criterion, flattened_filters
from resources.filter_item import FilterItem, FilterItemModel
from resources.sort import cleanup_sort, get_next_page_sort, reverse_sort
from resources.sort_item import SortItem, SortItemModel
from resources.filter_text_item import FilterTextItem, FilterTextItemModel
from image_files.models import ImageFileRef
import image_files.auth as img_file_auth
from itgs import Itgs
from resources.standard_text_operator import StandardTextOperator


class IntroductoryJourney(BaseModel):
    uid: str = Field(description="The primary stable external identifier for this row")
    journey: Journey = Field(
        description="The journey that can be selected for users introducing themselves to the app"
    )
    user_sub: Optional[str] = Field(
        description="The sub of the user who marked the journey as introductory, if they haven't since been deleted"
    )
    created_at: float = Field(
        description="The time at which the row was created, in seconds since the epoch"
    )


INTRODUCTORY_JOURNEY_SORT_OPTIONS = [
    SortItem[Literal["uid"], str],
    SortItem[Literal["journey_uid"], str],
    SortItem[Literal["journey_title"], float],
    SortItem[Literal["journey_created_at"], float],
    SortItem[Literal["created_at"], float],
]
IntroductoryJourneySortOption = Union[
    SortItemModel[Literal["uid"], str],
    SortItemModel[Literal["journey_uid"], str],
    SortItemModel[Literal["journey_title"], str],
    SortItemModel[Literal["journey_created_at"], float],
    SortItemModel[Literal["created_at"], float],
]


class IntroductoryJourneyFilter(BaseModel):
    uid: Optional[FilterTextItemModel] = Field(
        None, description="the uid of the introductory journey"
    )
    journey_uid: Optional[FilterTextItemModel] = Field(
        None, description="the uid of the journey"
    )
    journey_title: Optional[FilterTextItemModel] = Field(
        None, description="the title of the journey"
    )
    journey_created_at: Optional[FilterItemModel[float]] = Field(
        None, description="the time at which the journey was created"
    )
    journey_deleted_at: Optional[FilterItemModel[float]] = Field(
        None, description="the time at which the journey was deleted"
    )
    created_at: Optional[FilterItemModel[float]] = Field(
        None, description="the time at which the introductory journey was created"
    )


class ReadIntroductoryJourneyRequest(BaseModel):
    filters: IntroductoryJourneyFilter = Field(
        default_factory=IntroductoryJourneyFilter, description="the filters to apply"
    )
    sort: Optional[List[IntroductoryJourneySortOption]] = Field(
        None, description="the order to sort by"
    )
    limit: int = Field(
        15,
        description="the maximum number of items to return in the response",
        ge=1,
        le=150,
    )


class ReadIntroductoryJourneyResponse(BaseModel):
    items: List[IntroductoryJourney] = Field(
        description="the items matching the filters in the given sort"
    )
    next_page_sort: Optional[List[IntroductoryJourneySortOption]] = Field(
        description=(
            "if there is a next page or an earlier page, provides the necessary "
            "sort criteria to get it"
        )
    )


router = APIRouter()


@router.post(
    "/search",
    response_model=ReadIntroductoryJourneyResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_introductory_journeys(
    args: ReadIntroductoryJourneyRequest, authorization: Optional[str] = Header(None)
):
    """Lists out introductory journeys

    This requires standard authentication with an admin account.
    """
    sort = [srt.to_result() for srt in (args.sort or [])]
    sort = cleanup_sort(INTRODUCTORY_JOURNEY_SORT_OPTIONS, sort, ["uid", "journey_uid"])
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
        items = await raw_read_introductory_journeys(
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
            rev_items = await raw_read_introductory_journeys(
                itgs, filters_to_apply, rev_sort, 1
            )
            if rev_items:
                first_item = item_pseudocolumns(items[0])

        if first_item is not None or last_item is not None:
            next_page_sort = get_next_page_sort(first_item, last_item, sort)

        return Response(
            content=ReadIntroductoryJourneyResponse(
                items=items,
                next_page_sort=[s.to_model() for s in next_page_sort]
                if next_page_sort is not None
                else None,
            ).json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )


async def raw_read_introductory_journeys(
    itgs: Itgs,
    filters_to_apply: List[Tuple[str, Union[FilterItem, FilterTextItem]]],
    sort: List[SortItem],
    limit: int,
):
    """performs exactly the specified sort without pagination logic"""
    introductory_journeys = Table("introductory_journeys")
    introductory_journey_users = Table("users").as_("ij_users")
    journeys = Table("journeys")
    content_files = Table("content_files")
    image_files = Table("image_files")
    blurred_image_files = image_files.as_("blurred_image_files")
    darkened_image_files = image_files.as_("darkened_image_files")
    journey_subcategories = Table("journey_subcategories")
    instructors = Table("instructors")
    instructor_pictures = image_files.as_("instructor_pictures")
    daily_event_journeys = Table("daily_event_journeys")
    daily_events = Table("daily_events")
    samples = content_files.as_("samples")
    videos = content_files.as_("videos")
    interactive_prompts = Table("interactive_prompts")

    query: QueryBuilder = (
        Query.from_(introductory_journeys)
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
            samples.uid,
            videos.uid,
            darkened_image_files.uid,
            introductory_journeys.uid,
            introductory_journey_users.sub,
            introductory_journeys.created_at,
        )
        .join(journeys)
        .on(journeys.id == introductory_journeys.journey_id)
        .join(interactive_prompts)
        .on(interactive_prompts.id == journeys.interactive_prompt_id)
        .join(content_files)
        .on(content_files.id == journeys.audio_content_file_id)
        .join(image_files)
        .on(image_files.id == journeys.background_image_file_id)
        .join(blurred_image_files)
        .on(blurred_image_files.id == journeys.blurred_background_image_file_id)
        .join(darkened_image_files)
        .on(darkened_image_files.id == journeys.darkened_background_image_file_id)
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
        .left_outer_join(samples)
        .on(samples.id == journeys.sample_content_file_id)
        .left_outer_join(videos)
        .on(videos.id == journeys.video_content_file_id)
        .left_outer_join(introductory_journey_users)
        .on(introductory_journey_users.id == introductory_journeys.user_id)
    )

    qargs = []

    def pseudocolumn(key: str) -> Term:
        if key in ("uid", "created_at"):
            return introductory_journeys.field(key)
        elif key in (
            "journey_uid",
            "journey_title",
            "journey_description",
            "journey_created_at",
            "journey_deleted_at",
        ):
            return journeys.field(key[len("journey_") :])
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
            return Function("json_extract", interactive_prompts.prompt, "style")
        elif key == "daily_event_uid":
            return daily_events.uid
        elif key == "blurred_background_image_file_uid":
            return blurred_image_files.uid
        elif key == "darkened_background_image_file_uid":
            return darkened_image_files.uid
        elif key == "sample_content_file_uid":
            return samples.uid
        elif key == "video_content_file_uid":
            return videos.uid
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
    items: List[IntroductoryJourney] = []
    for row in response.results or []:
        items.append(
            IntroductoryJourney(
                journey=Journey(
                    uid=row[0],
                    audio_content=ContentFileRef(
                        uid=row[1],
                        jwt=await content_files_auth.create_jwt(itgs, row[1]),
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
                        uid=row[17],
                        jwt=await image_files_auth.create_jwt(itgs, row[17]),
                    ),
                    sample=(
                        ContentFileRef(
                            uid=row[18],
                            jwt=await content_files_auth.create_jwt(itgs, row[18]),
                        )
                        if row[18] is not None
                        else None
                    ),
                    video=(
                        ContentFileRef(
                            uid=row[19],
                            jwt=await content_files_auth.create_jwt(itgs, row[19]),
                        )
                        if row[19] is not None
                        else None
                    ),
                    darkened_background_image=ImageFileRef(
                        uid=row[20],
                        jwt=await image_files_auth.create_jwt(itgs, row[20]),
                    ),
                ),
                uid=row[21],
                user_sub=row[22],
                created_at=row[23],
            )
        )
    return items


def item_pseudocolumns(item: IntroductoryJourney) -> dict:
    """Returns the dictified item such that the keys in the returned dict
    match the keys of the sort options
    """
    return {
        "uid": item.uid,
        "journey_uid": item.journey.uid,
        "journey_title": item.journey.title,
        "journey_created_at": item.journey.created_at,
        "created_at": item.created_at,
    }
