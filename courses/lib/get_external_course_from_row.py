from typing import Optional, Tuple
from courses.models.external_course import ExternalCourse, ExternalCourseInstructor
from image_files.models import ImageFileRef
import image_files.auth as image_files_auth
from content_files.models import ContentFileRef
import content_files.auth as content_files_auth
from transcripts.models.transcript_ref import TranscriptRef
import transcripts.auth as transcripts_auth
from itgs import Itgs
from dataclasses import dataclass
import users.lib.entitlements as entitlements_lib


def create_standard_external_course_query(user_sub: Optional[str]) -> Tuple[str, list]:
    """Creates the standard query required to get the data about an external course,
    where the next part should be WHERE

    Returns:
        (str, list): (query, qargs)
    """
    return (
        """
SELECT
    courses.uid,
    courses.slug,
    courses.title,
    courses.description,
    instructors.uid,
    instructors.name,
    course_darkened_background_images.uid,
    course_logo_images.uid,
    courses.revenue_cat_entitlement,
    course_users.created_at,
    user_course_likes.created_at,
    courses.created_at,
    (
        SELECT COUNT(*) FROM course_journeys
        WHERE course_journeys.course_id = courses.id
    ) AS num_journeys,
    intro_videos.uid,
    intro_videos.duration_seconds,
    intro_video_transcripts.uid,
    intro_video_thumbnails.uid,
    intro_video_thumbnail_exports.thumbhash
FROM courses
JOIN instructors ON instructors.id = courses.instructor_id
LEFT OUTER JOIN users ON users.sub = ?
LEFT OUTER JOIN image_files AS course_darkened_background_images ON course_darkened_background_images.id = courses.background_darkened_image_file_id
LEFT OUTER JOIN image_files AS course_logo_images ON course_logo_images.id = courses.logo_image_file_id
LEFT OUTER JOIN course_users ON (course_users.course_id = courses.id AND course_users.user_id = users.id)
LEFT OUTER JOIN user_course_likes ON (user_course_likes.course_id = courses.id AND user_course_likes.user_id = users.id)
LEFT OUTER JOIN content_files AS intro_videos ON intro_videos.id = courses.video_content_file_id
LEFT OUTER JOIN transcripts AS intro_video_transcripts ON (
    EXISTS (
        SELECT 1 FROM content_file_transcripts
        WHERE
            content_file_transcripts.content_file_id = intro_videos.id
            AND content_file_transcripts.transcript_id = intro_video_transcripts.id
    )
)
LEFT OUTER JOIN image_files AS intro_video_thumbnails ON intro_video_thumbnails.id = intro_videos.video_thumbnail_image_file_id
LEFT OUTER JOIN image_file_exports AS intro_video_thumbnail_exports ON (
    intro_video_thumbnail_exports.image_file_id = intro_video_thumbnails.id
    AND intro_video_thumbnail_exports.width = 180
    AND intro_video_thumbnail_exports.height = 368
    AND NOT EXISTS (
        SELECT 1 FROM image_file_exports AS other_exports
        WHERE
            other_exports.image_file_id = intro_video_thumbnails.id
            AND other_exports.width = 180
            AND other_exports.height = 368
            AND other_exports.uid < intro_video_thumbnail_exports.uid
    )
)
    """,
        [user_sub],
    )


@dataclass
class ExternalCourseRow:
    uid: str
    slug: str
    title: str
    description: str
    instructor_uid: str
    instructor_name: str
    background_image_uid: Optional[str]
    logo_image_uid: Optional[str]
    revenue_cat_entitlement: str
    joined_at: Optional[float]
    liked_at: Optional[float]
    created_at: float
    num_journeys: int
    intro_video_uid: Optional[str]
    intro_video_duration_seconds: Optional[int]
    intro_video_transcript_uid: Optional[str]
    intro_video_thumbnail_uid: Optional[str]
    intro_video_thumbhash: Optional[str]


async def get_external_course_from_row(
    itgs: Itgs, *, user_sub: Optional[str], row: ExternalCourseRow
) -> ExternalCourse:
    """Gets the internal course using the data returned from the database, filling
    in defaults as necessary.

    The arguments are similar to those of externalcourse, so check there for docs.
    """
    if row.background_image_uid is None:
        # abstract-darkened public image
        row.background_image_uid = "oseh_if_0ykGW_WatP5-mh-0HRsrNw"

    entitlement = (
        None
        if user_sub is None
        else await entitlements_lib.get_entitlement(
            itgs, user_sub=user_sub, identifier=row.revenue_cat_entitlement
        )
    )
    has_entitlement = entitlement is not None and entitlement.is_active

    return ExternalCourse(
        uid=row.uid,
        slug=row.slug,
        title=row.title,
        description=row.description,
        instructor=ExternalCourseInstructor(
            uid=row.instructor_uid, name=row.instructor_name
        ),
        background_image=ImageFileRef(
            uid=row.background_image_uid,
            jwt=await image_files_auth.create_jwt(itgs, row.background_image_uid),
        ),
        logo=(
            None
            if row.logo_image_uid is None
            else ImageFileRef(
                uid=row.logo_image_uid,
                jwt=await image_files_auth.create_jwt(itgs, row.logo_image_uid),
            )
        ),
        revenue_cat_entitlement=row.revenue_cat_entitlement,
        has_entitlement=has_entitlement,
        joined_at=row.joined_at,
        liked_at=row.liked_at,
        created_at=row.created_at,
        num_journeys=row.num_journeys,
        intro_video=(
            None
            if row.intro_video_uid is None
            else ContentFileRef(
                uid=row.intro_video_uid,
                jwt=await content_files_auth.create_jwt(itgs, row.intro_video_uid),
            )
        ),
        intro_video_duration=row.intro_video_duration_seconds,
        intro_video_transcript=(
            None
            if row.intro_video_transcript_uid is None
            else TranscriptRef(
                uid=row.intro_video_transcript_uid,
                jwt=await transcripts_auth.create_jwt(
                    itgs, row.intro_video_transcript_uid
                ),
            )
        ),
        intro_video_thumbnail=(
            None
            if row.intro_video_thumbnail_uid is None
            else ImageFileRef(
                uid=row.intro_video_thumbnail_uid,
                jwt=await image_files_auth.create_jwt(
                    itgs, row.intro_video_thumbnail_uid
                ),
            )
        ),
        intro_video_thumbhash=row.intro_video_thumbhash,
    )
