import secrets
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, validator
from typing import Annotated, Dict, Iterable, Optional, Literal, cast, get_args
from auth import auth_admin
from content_files.models import ContentFileRef
from courses.models.internal_course import InternalCourse, InternalCourseInstructor
from image_files.models import ImageFileRef
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from itgs import Itgs
from journeys.models.series_flags import SeriesFlags
import image_files.auth as image_files_auth
import content_files.auth as content_files_auth

router = APIRouter()


class CreateCourseRequest(BaseModel):
    slug: str = Field(description="A chosen unique identifier, may be included in URLs")
    flags: int = Field(
        description="The access flags for the course as a twos-complement 64-bit integer"
    )
    revenue_cat_entitlement: str = Field(
        description="The name of the entitlement on revenuecat required for this course"
    )
    title: str = Field(description="The title of the course, used standalone")
    description: str = Field(
        description="A roughly 400 character description for the course"
    )
    instructor_uid: str = Field(description="The UID of the instructor for this course")
    background_image_uid: str = Field(
        description="The UID of the row in course_backgrounds to get the original and darkened background images from"
    )
    video_uid: str = Field(
        description="The UID of the row in course_videos to get the video content file from",
    )
    video_thumbnail_uid: str = Field(
        description="The UID of the row in course_video_thumbnail_images to get the video thumbnail image from",
    )
    logo_uid: str = Field(
        description="The UID of the row in course_logo_images to get the logo image from",
    )
    hero_uid: str = Field(
        description="The UID of the row in course_heroes to get the hero image from",
    )

    @validator("flags")
    def flags_contains_only_valid_bits(cls, v: int) -> int:
        valid_flags = 0
        for val in SeriesFlags:
            valid_flags |= int(val)
        if v & valid_flags != v:
            raise ValueError(f"the following flags are invalid: {v & ~valid_flags:b}")
        return v


ERROR_404_TYPES = Literal[
    "instructor_not_found",
    "background_not_found",
    "video_not_found",
    "video_thumbnail_not_found",
    "logo_not_found",
    "hero_not_found",
]
ERROR_409_TYPES = Literal["course_slug_exists"]

ERROR_404_RESPONSES = dict(
    (
        err_type,
        Response(
            status_code=404,
            content=StandardErrorResponse[ERROR_404_TYPES](
                type=err_type,
                message=f"there is no {err_type[:-len('_not_found')]} with that UID",
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        ),
    )
    for err_type in cast(Iterable[ERROR_404_TYPES], get_args(ERROR_404_TYPES))
)

ERROR_409_RESPONSES: Dict[ERROR_409_TYPES, Response] = {
    "course_slug_exists": Response(
        status_code=409,
        content=StandardErrorResponse[ERROR_409_TYPES](
            type="course_slug_exists",
            message="a course with that slug already exists",
        ).model_dump_json(),
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
}


@router.post(
    "/",
    response_model=InternalCourse,
    status_code=201,
    responses={
        "404": {
            "description": "One of the subresources was not found",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        "409": {
            "description": "A course with that slug already exists",
            "model": StandardErrorResponse[ERROR_409_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def create_course(
    args: CreateCourseRequest, authorization: Annotated[Optional[str], Header()] = None
):
    """Creates a new course using the given parameters. Although subresources are
    all specified using the course-specific uids to ensure they have already been
    properly processed, they will be stored as direct references to the actual
    image or content files.

    Requires standard authorization for an admin user.
    """
    request_at = time.time()

    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor("strong")

        new_course_uid = f"oseh_c_{secrets.token_urlsafe(16)}"

        response = await cursor.executeunified3(
            (
                (
                    """
SELECT
    instructors.name,
    image_files.uid
FROM instructors
LEFT OUTER JOIN image_files ON image_files.id = instructors.picture_image_file_id
WHERE
    instructors.uid = ?
                """,
                    (args.instructor_uid,),
                ),
                (
                    """
SELECT
    original_image_files.uid,
    darkened_image_files.uid
FROM 
    course_background_images, 
    image_files AS original_image_files, 
    image_files AS darkened_image_files
WHERE
    course_background_images.uid = ?
    AND course_background_images.original_image_file_id = original_image_files.id
    AND course_background_images.darkened_image_file_id = darkened_image_files.id
                    """,
                    (args.background_image_uid,),
                ),
                (
                    """
SELECT
    content_files.uid
FROM course_videos, content_files
WHERE
    course_videos.uid = ?
    AND course_videos.content_file_id = content_files.id
                    """,
                    (args.video_uid,),
                ),
                (
                    """
SELECT
    image_files.uid
FROM course_video_thumbnail_images, image_files
WHERE
    course_video_thumbnail_images.uid = ?
    AND course_video_thumbnail_images.image_file_id = image_files.id
                    """,
                    (args.video_thumbnail_uid,),
                ),
                (
                    """
SELECT
    image_files.uid
FROM course_logo_images, image_files
WHERE
    course_logo_images.uid = ?
    AND course_logo_images.image_file_id = image_files.id
                    """,
                    (args.logo_uid,),
                ),
                (
                    """
SELECT
    image_files.uid
FROM course_hero_images, image_files
WHERE
    course_hero_images.uid = ?
    AND course_hero_images.image_file_id = image_files.id
                    """,
                    (args.hero_uid,),
                ),
                (
                    """
SELECT
    1
FROM courses
WHERE
    courses.slug = ?
                    """,
                    (args.slug,),
                ),
                (
                    """
INSERT INTO courses (
    uid, 
    slug, 
    flags, 
    revenue_cat_entitlement, 
    title, 
    description,
    instructor_id,
    background_original_image_file_id,
    background_darkened_image_file_id,
    video_content_file_id,
    video_thumbnail_image_file_id,
    logo_image_file_id,
    hero_image_file_id,
    created_at
)
SELECT
    ?,
    ?,
    ?,
    ?,
    ?,
    ?,
    instructors.id,
    original_image_files.id,
    darkened_image_files.id,
    content_files.id,
    video_thumbnail_image_files.id,
    logo_image_files.id,
    hero_image_files.id,
    ?
FROM
    instructors,
    image_files AS original_image_files,
    image_files AS darkened_image_files,
    content_files,
    image_files AS video_thumbnail_image_files,
    image_files AS logo_image_files,
    image_files AS hero_image_files
WHERE
    instructors.uid = ?
    AND EXISTS (
        SELECT 1 FROM course_background_images
        WHERE
            course_background_images.uid = ?
            AND course_background_images.original_image_file_id = original_image_files.id
            AND course_background_images.darkened_image_file_id = darkened_image_files.id
    )
    AND EXISTS (
        SELECT 1 FROM course_videos
        WHERE
            course_videos.uid = ?
            AND course_videos.content_file_id = content_files.id
    )
    AND EXISTS (
        SELECT 1 FROM course_video_thumbnail_images
        WHERE
            course_video_thumbnail_images.uid = ?
            AND course_video_thumbnail_images.image_file_id = video_thumbnail_image_files.id
    )
    AND EXISTS (
        SELECT 1 FROM course_logo_images
        WHERE
            course_logo_images.uid = ?
            AND course_logo_images.image_file_id = logo_image_files.id
    )
    AND EXISTS (
        SELECT 1 FROM course_hero_images
        WHERE
            course_hero_images.uid = ?
            AND course_hero_images.image_file_id = hero_image_files.id
    )
    AND NOT EXISTS (
        SELECT 1 FROM courses
        WHERE
            courses.slug = ?
    )
                    """,
                    (
                        new_course_uid,
                        args.slug,
                        args.flags,
                        args.revenue_cat_entitlement,
                        args.title,
                        args.description,
                        request_at,
                        args.instructor_uid,
                        args.background_image_uid,
                        args.video_uid,
                        args.video_thumbnail_uid,
                        args.logo_uid,
                        args.hero_uid,
                        args.slug,
                    ),
                ),
            )
        )

        instructor_response = response.items[0]
        background_response = response.items[1]
        video_response = response.items[2]
        video_thumbnail_response = response.items[3]
        logo_response = response.items[4]
        hero_response = response.items[5]
        slug_exists_response = response.items[6]
        insert_response = response.items[7]

        if (
            insert_response.rows_affected is not None
            and insert_response.rows_affected > 0
        ):
            assert instructor_response.results, response
            assert background_response.results, response
            assert video_response.results, response
            assert video_thumbnail_response.results, response
            assert logo_response.results, response
            assert hero_response.results, response
            assert not slug_exists_response.results, response

            instructor_name = cast(str, instructor_response.results[0][0])
            instructor_picture_uid = cast(
                Optional[str], instructor_response.results[0][1]
            )
            background_original_uid = cast(str, background_response.results[0][0])
            background_darkened_uid = cast(str, background_response.results[0][1])
            video_uid = cast(str, video_response.results[0][0])
            video_thumbnail_uid = cast(str, video_thumbnail_response.results[0][0])
            logo_uid = cast(str, logo_response.results[0][0])
            hero_uid = cast(str, hero_response.results[0][0])

            return Response(
                content=InternalCourse.__pydantic_serializer__.to_json(
                    InternalCourse(
                        uid=new_course_uid,
                        slug=args.slug,
                        flags=args.flags,
                        revenue_cat_entitlement=args.revenue_cat_entitlement,
                        title=args.title,
                        description=args.description,
                        instructor=InternalCourseInstructor(
                            uid=args.instructor_uid,
                            name=instructor_name,
                            picture=(
                                None
                                if instructor_picture_uid is None
                                else ImageFileRef(
                                    uid=instructor_picture_uid,
                                    jwt=await image_files_auth.create_jwt(
                                        itgs, instructor_picture_uid
                                    ),
                                )
                            ),
                        ),
                        background_original_image=ImageFileRef(
                            uid=background_original_uid,
                            jwt=await image_files_auth.create_jwt(
                                itgs, background_original_uid
                            ),
                        ),
                        background_darkened_image=ImageFileRef(
                            uid=background_darkened_uid,
                            jwt=await image_files_auth.create_jwt(
                                itgs, background_darkened_uid
                            ),
                        ),
                        video_content=ContentFileRef(
                            uid=video_uid,
                            jwt=await content_files_auth.create_jwt(itgs, video_uid),
                        ),
                        video_thumbnail=ImageFileRef(
                            uid=video_thumbnail_uid,
                            jwt=await image_files_auth.create_jwt(
                                itgs, video_thumbnail_uid
                            ),
                        ),
                        logo_image=ImageFileRef(
                            uid=logo_uid,
                            jwt=await image_files_auth.create_jwt(itgs, logo_uid),
                        ),
                        hero_image=ImageFileRef(
                            uid=hero_uid,
                            jwt=await image_files_auth.create_jwt(itgs, hero_uid),
                        ),
                        created_at=request_at,
                    )
                ),
                status_code=201,
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        if not instructor_response.results:
            return ERROR_404_RESPONSES["instructor_not_found"]

        if not background_response.results:
            return ERROR_404_RESPONSES["background_not_found"]

        if not video_response.results:
            return ERROR_404_RESPONSES["video_not_found"]

        if not video_thumbnail_response.results:
            return ERROR_404_RESPONSES["video_thumbnail_not_found"]

        if not logo_response.results:
            return ERROR_404_RESPONSES["logo_not_found"]

        if not hero_response.results:
            return ERROR_404_RESPONSES["hero_not_found"]

        if slug_exists_response.results:
            return ERROR_409_RESPONSES["course_slug_exists"]

        raise Exception(f"unexpected response: {response!r}")
