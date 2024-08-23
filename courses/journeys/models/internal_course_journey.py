from pydantic import BaseModel, Field
from typing import List
from content_files.models import ContentFileRef
import content_files.auth as content_files_auth
from image_files.models import ImageFileRef
import image_files.auth as image_files_auth
from instructors.routes.read import Instructor
from itgs import Itgs
from journeys.routes.read import Journey
from rqdb.result import ResultItem
import json
from journeys.subcategories.routes.read import JourneySubcategory


class InternalCourseJourney(BaseModel):
    """Internal representation of a course journey"""

    association_uid: str = Field(
        description=(
            "The unique identifier for the association between the course and the journey"
        )
    )
    course_uid: str = Field(description="The unique identifier for the course")
    journey: Journey = Field(description="The actual journey within the course")
    priority: int = Field(
        description="Journeys with lower priority values are generally taken first"
    )


def create_read_select() -> str:
    return """
SELECT
    course_journeys.uid,
    courses.uid,
    course_journeys.priority,
    journeys.uid,
    audio_contents.uid,
    background_images.uid,
    blurred_background_images.uid,
    darkened_background_images.uid,
    journey_subcategories.uid,
    journey_subcategories.internal_name,
    journey_subcategories.external_name,
    journey_subcategories.bias,
    instructors.uid,
    instructors.name,
    instructors.bias,
    instructor_pictures.uid,
    instructors.created_at,
    instructors.flags,
    journeys.title,
    journeys.description,
    audio_contents.duration_seconds,
    interactive_prompts.prompt,
    journeys.created_at,
    journeys.deleted_at,
    introductory_journeys.uid,
    samples.uid,
    videos.uid,
    journeys.special_category,
    variation_journeys.uid
FROM course_journeys
JOIN journeys ON journeys.id = course_journeys.journey_id
JOIN courses ON courses.id = course_journeys.course_id
JOIN content_files AS audio_contents ON audio_contents.id = journeys.audio_content_file_id
JOIN image_files AS background_images ON background_images.id = journeys.background_image_file_id
JOIN image_files AS blurred_background_images ON blurred_background_images.id = journeys.blurred_background_image_file_id
JOIN image_files AS darkened_background_images ON darkened_background_images.id = journeys.darkened_background_image_file_id
JOIN journey_subcategories ON journey_subcategories.id = journeys.journey_subcategory_id
JOIN instructors ON instructors.id = journeys.instructor_id
JOIN interactive_prompts ON interactive_prompts.id = journeys.interactive_prompt_id
LEFT OUTER JOIN image_files AS instructor_pictures ON instructor_pictures.id = instructors.picture_image_file_id
LEFT OUTER JOIN introductory_journeys ON introductory_journeys.journey_id = journeys.id
LEFT OUTER JOIN content_files AS samples ON samples.id = journeys.sample_content_file_id
LEFT OUTER JOIN content_files AS videos ON videos.id = journeys.video_content_file_id
LEFT OUTER JOIN journeys AS variation_journeys ON variation_journeys.id = journeys.variation_of_journey_id
        """


async def parse_read_result(
    itgs: Itgs, item: ResultItem
) -> List[InternalCourseJourney]:
    return [
        InternalCourseJourney(
            association_uid=row[0],
            course_uid=row[1],
            priority=row[2],
            journey=Journey(
                uid=row[3],
                audio_content=ContentFileRef(
                    uid=row[4], jwt=await content_files_auth.create_jwt(itgs, row[4])
                ),
                background_image=ImageFileRef(
                    uid=row[5], jwt=await image_files_auth.create_jwt(itgs, row[5])
                ),
                blurred_background_image=ImageFileRef(
                    uid=row[6], jwt=await image_files_auth.create_jwt(itgs, row[6])
                ),
                darkened_background_image=ImageFileRef(
                    uid=row[7], jwt=await image_files_auth.create_jwt(itgs, row[7])
                ),
                subcategory=JourneySubcategory(
                    uid=row[8],
                    internal_name=row[9],
                    external_name=row[10],
                    bias=row[11],
                ),
                instructor=Instructor(
                    uid=row[12],
                    name=row[13],
                    bias=row[14],
                    picture=(
                        None
                        if row[15] is None
                        else ImageFileRef(
                            uid=row[15],
                            jwt=await image_files_auth.create_jwt(itgs, row[15]),
                        )
                    ),
                    created_at=row[16],
                    flags=row[17],
                ),
                title=row[18],
                description=row[19],
                duration_seconds=row[20],
                prompt=json.loads(row[21]),
                created_at=row[22],
                deleted_at=row[23],
                introductory_journey_uid=row[24],
                sample=(
                    None
                    if row[25] is None
                    else ContentFileRef(
                        uid=row[25],
                        jwt=await content_files_auth.create_jwt(itgs, row[25]),
                    )
                ),
                video=(
                    None
                    if row[26] is None
                    else ContentFileRef(
                        uid=row[26],
                        jwt=await content_files_auth.create_jwt(itgs, row[26]),
                    )
                ),
                special_category=row[27],
                variation_of_journey_uid=row[28],
            ),
        )
        for row in item.results or []
    ]
