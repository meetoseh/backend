from pypika import Table, Query, Parameter
from pypika.queries import QueryBuilder
from pypika.terms import Term
from typing import Annotated, Any, Dict, List, Literal, Optional, Tuple, Union, cast
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from auth import auth_admin
from content_files.models import ContentFileRef
from courses.journeys.models.internal_course_journey import InternalCourseJourney
from instructors.routes.read import Instructor
from journeys.routes.read import Journey
from journeys.subcategories.routes.read import JourneySubcategory
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
import content_files.auth as content_files_auth
from content_files.models import ContentFileRef
import json


COURSE_JOURNEY_SORT_OPTIONS = [
    SortItem[Literal["uid"], str],
    SortItem[Literal["course_uid"], str],
    SortItem[Literal["journey_uid"], str],
    SortItem[Literal["course_title"], str],
    SortItem[Literal["priority"], int],
]
CourseJourneySortOption = Union[
    SortItemModel[Literal["uid"], str],
    SortItemModel[Literal["course_uid"], str],
    SortItemModel[Literal["journey_uid"], str],
    SortItemModel[Literal["course_title"], str],
    SortItemModel[Literal["priority"], int],
]


class CourseJourneyFilter(BaseModel):
    uid: Optional[FilterTextItemModel] = Field(
        None, description="the uid of the course journey association."
    )
    course_uid: Optional[FilterTextItemModel] = Field(
        None, description="the uid of the course"
    )
    course_title: Optional[FilterTextItemModel] = Field(
        None, description="the title of the course"
    )
    journey_uid: Optional[FilterTextItemModel] = Field(
        None, description="the uid of the journey"
    )
    journey_title: Optional[FilterTextItemModel] = Field(
        None, description="the title of the journey"
    )
    priority: Optional[FilterItemModel[int]] = Field(
        None,
        description="the priority of the journey within the course; lower priorities are taken first",
    )


class ReadCourseJourneyRequest(BaseModel):
    filters: CourseJourneyFilter = Field(
        default_factory=lambda: CourseJourneyFilter.model_validate({}),
        description="the filters to apply",
    )
    sort: Optional[List[CourseJourneySortOption]] = Field(
        None, description="the sort order to apply"
    )
    limit: int = Field(
        25, description="the maximum number of rows to return", ge=1, le=250
    )


class ReadCourseJourneyResponse(BaseModel):
    items: List[InternalCourseJourney] = Field(
        description="the items matching the filters in the given sort"
    )
    next_page_sort: Optional[List[CourseJourneySortOption]] = Field(
        None, description="if there is a next or earlier page, the sort order to get it"
    )


router = APIRouter()


@router.post(
    "/search",
    response_model=ReadCourseJourneyResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_course_journeys(
    args: ReadCourseJourneyRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Lists out course journeys

    This requires standard authorization for a user with admin access
    """
    sort = [srt.to_result() for srt in (args.sort or [])]
    sort = cleanup_sort(COURSE_JOURNEY_SORT_OPTIONS, sort, ["uid"])
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
        items = await raw_read_course_journeys(
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
            rev_items = await raw_read_course_journeys(
                itgs, filters_to_apply, rev_sort, 1
            )
            if rev_items:
                first_item = item_pseudocolumns(items[0])

        if first_item is not None or last_item is not None:
            next_page_sort = get_next_page_sort(first_item, last_item, sort)

        return Response(
            content=ReadCourseJourneyResponse.__pydantic_serializer__.to_json(
                ReadCourseJourneyResponse(
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


async def raw_read_course_journeys(
    itgs: Itgs,
    filters_to_apply: List[Tuple[str, FilterItemLike]],
    sort: List[SortItem],
    limit: int,
) -> List[InternalCourseJourney]:
    """performs exactly the specified sort without pagination logic"""
    course_journeys = Table("course_journeys")
    courses = Table("courses")
    journeys = Table("journeys")
    content_files = Table("content_files")
    image_files = Table("image_files")
    blurred_image_files = image_files.as_("blurred_image_files")
    darkened_image_files = image_files.as_("darkened_image_files")
    journey_subcategories = Table("journey_subcategories")
    instructors = Table("instructors")
    instructor_pictures = image_files.as_("instructor_pictures")
    samples = content_files.as_("samples")
    videos = content_files.as_("videos")
    introductory_journeys = Table("introductory_journeys")
    interactive_prompt_sessions = Table("interactive_prompt_sessions")
    interactive_prompts = Table("interactive_prompts")
    variation_journeys = journeys.as_("variation_journeys")

    query: QueryBuilder = (
        Query.from_(course_journeys)
        .select(
            course_journeys.uid,
            courses.uid,
            course_journeys.priority,
            journeys.uid,
            content_files.uid,
            image_files.uid,
            journey_subcategories.uid,
            journey_subcategories.internal_name,
            journey_subcategories.external_name,
            journey_subcategories.bias,
            instructors.uid,
            instructors.name,
            instructor_pictures.uid,
            instructors.created_at,
            instructors.deleted_at,
            instructors.bias,
            journeys.title,
            journeys.description,
            content_files.duration_seconds,
            interactive_prompts.prompt,
            journeys.created_at,
            journeys.deleted_at,
            blurred_image_files.uid,
            darkened_image_files.uid,
            samples.uid,
            videos.uid,
            introductory_journeys.uid,
            journeys.special_category,
            variation_journeys.uid,
        )
        .join(courses)
        .on(courses.id == course_journeys.course_id)
        .join(journeys)
        .on(journeys.id == course_journeys.journey_id)
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
        .join(interactive_prompts)
        .on(journeys.interactive_prompt_id == interactive_prompts.id)
        .left_outer_join(instructor_pictures)
        .on(instructor_pictures.id == instructors.picture_image_file_id)
        .left_outer_join(samples)
        .on(samples.id == journeys.sample_content_file_id)
        .left_outer_join(videos)
        .on(videos.id == journeys.video_content_file_id)
        .left_outer_join(introductory_journeys)
        .on(introductory_journeys.journey_id == journeys.id)
        .left_outer_join(variation_journeys)
        .on(variation_journeys.id == journeys.variation_of_journey_id)
    )
    qargs = []

    def pseudocolumn(key: str) -> Term:
        if key in ("uid", "association_uid"):
            return course_journeys.uid
        elif key == "course_uid":
            return courses.uid
        elif key == "course_title":
            return courses.title
        elif key == "journey_uid":
            return journeys.uid
        elif key == "journey_title":
            return journeys.title
        elif key == "priority":
            return course_journeys.priority

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
    items: List[InternalCourseJourney] = []
    for row in response.results or []:
        association_uid = cast(str, row[0])
        course_uid = cast(str, row[1])
        priority = cast(int, row[2])
        row = row[3:]
        journey = Journey(
            uid=row[0],
            audio_content=ContentFileRef(
                uid=row[1], jwt=await content_files_auth.create_jwt(itgs, row[1])
            ),
            background_image=ImageFileRef(
                uid=row[2], jwt=await image_files_auth.create_jwt(itgs, row[2])
            ),
            subcategory=JourneySubcategory(
                uid=row[3], internal_name=row[4], external_name=row[5], bias=row[6]
            ),
            instructor=Instructor(
                uid=row[7],
                name=row[8],
                picture=(
                    ImageFileRef(
                        uid=row[9],
                        jwt=await image_files_auth.create_jwt(itgs, row[9]),
                    )
                    if row[9] is not None
                    else None
                ),
                created_at=row[10],
                deleted_at=row[11],
                bias=row[12],
            ),
            title=row[13],
            description=row[14],
            duration_seconds=row[15],
            prompt=json.loads(row[16]),
            created_at=row[17],
            deleted_at=row[18],
            blurred_background_image=ImageFileRef(
                uid=row[19], jwt=await image_files_auth.create_jwt(itgs, row[19])
            ),
            darkened_background_image=ImageFileRef(
                uid=row[20], jwt=await image_files_auth.create_jwt(itgs, row[20])
            ),
            sample=(
                ContentFileRef(
                    uid=row[21],
                    jwt=await content_files_auth.create_jwt(itgs, row[21]),
                )
                if row[21] is not None
                else None
            ),
            video=(
                ContentFileRef(
                    uid=row[22],
                    jwt=await content_files_auth.create_jwt(itgs, row[22]),
                )
                if row[22] is not None
                else None
            ),
            introductory_journey_uid=row[23],
            special_category=row[24],
            variation_of_journey_uid=row[25],
        )

        items.append(
            InternalCourseJourney(
                association_uid=association_uid,
                course_uid=course_uid,
                priority=priority,
                journey=journey,
            )
        )
    return items


def item_pseudocolumns(item: InternalCourseJourney) -> dict:
    """returns the dictified item such that the keys in the return dict match
    the keys of the sort options"""
    return {
        "uid": item.association_uid,
        "course_uid": item.course_uid,
        "journey_uid": item.journey.uid,
        "course_title": item.journey.title,
        "priority": item.priority,
    }
