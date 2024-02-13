from typing import Optional
from courses.models.external_course import ExternalCourse
from image_files.models import ImageFileRef
from image_files.auth import create_jwt as create_image_file_jwt
from itgs import Itgs


async def get_external_course_from_row(
    itgs: Itgs,
    *,
    uid: str,
    slug: str,
    title: str,
    description: str,
    background_image_uid: Optional[str],
) -> ExternalCourse:
    """Gets the internal course using the data returned from the database, filling
    in defaults as necessary.

    The arguments are similar to those of externalcourse, so check there for docs.
    """
    if background_image_uid is None:
        # abstract-darkened public image
        background_image_uid = "oseh_if_0ykGW_WatP5-mh-0HRsrNw"

    return ExternalCourse(
        uid=uid,
        slug=slug,
        title=title,
        description=description,
        background_image=ImageFileRef(
            uid=background_image_uid,
            jwt=await create_image_file_jwt(itgs, image_file_uid=background_image_uid),
        ),
    )
