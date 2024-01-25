import secrets
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, StringConstraints
from typing import Optional, Literal, Annotated, cast as typing_cast
from auth import auth_admin
from image_files.models import ImageFileRef
import image_files.auth
from content_files.models import ContentFileRef
import content_files.auth
from instructors.routes.read import Instructor
from itgs import Itgs
from journeys.lib.slugs import assign_slug_from_title
from journeys.subcategories.routes.read import JourneySubcategory
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from interactive_prompts.models.prompt import Prompt
import journeys.lib.stats
import time


router = APIRouter()


class CreateJourneyRequest(BaseModel):
    journey_audio_content_uid: str = Field(
        description="The UID of the journey audio content to be used for this journey"
    )
    journey_background_image_uid: str = Field(
        description="The UID of the journey background image to be used for this journey"
    )
    journey_subcategory_uid: str = Field(
        description="The UID of the journey subcategory this journey belongs to"
    )
    instructor_uid: str = Field(
        description="The UID of the instructor we are crediting for this journey"
    )
    title: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=48)
    ] = Field(description="The display title")
    description: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
    ] = Field(description="The display description")
    prompt: Prompt = Field(
        description="The prompt style, text, and options to display to the user"
    )
    lobby_duration_seconds: int = Field(
        10, description="The duration of the lobby in seconds.", ge=5, le=300
    )
    variation_of_journey_uid: Optional[str] = Field(
        description=(
            "If this journey is a variation on another journey, the uid of the "
            "original journey. Must not be deleted or be a variation itself."
        )
    )


class CreateJourneyResponse(BaseModel):
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
        description="The image file for the blurred background of the journey"
    )
    darkened_background_image: ImageFileRef = Field(
        description="The image file for the darkened background of the journey"
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
    lobby_duration_seconds: int = Field(
        description="The duration of the lobby in seconds.",
    )
    created_at: float = Field(
        description="The timestamp of when this journey was created"
    )
    sample: Optional[ContentFileRef] = Field(
        description=(
            "If the sample for the journey has been generated, the content "
            "file containing the sample video, otherwise null"
        )
    )
    video: Optional[ContentFileRef] = Field(
        description=(
            "If the full length video for the journey has been generated, "
            "the content file containing the full length video, otherwise null"
        )
    )
    variation_of_journey_uid: Optional[str] = Field(
        description=(
            "If this journey is a variation on another journey, the uid of the "
            "original journey."
        )
    )


ERROR_404_TYPES = Literal[
    "journey_audio_content_not_found",
    "journey_background_image_not_found",
    "journey_subcategory_not_found",
    "instructor_not_found",
    "variation_journey_not_found",
]

ERROR_409_TYPES = Literal[
    "variation_journey_deleted",
    "variation_journey_is_variation",
]


ERROR_503_TYPES = Literal["raced"]


@router.post(
    "/",
    status_code=201,
    response_model=CreateJourneyResponse,
    responses={
        "404": {
            "model": StandardErrorResponse[ERROR_404_TYPES],
            "description": "A necessary subresource is missing",
        },
        "409": {
            "model": StandardErrorResponse[ERROR_409_TYPES],
            "description": "A necessary subresource is in an invalid state",
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def create_journey(
    args: CreateJourneyRequest, authorization: Optional[str] = Header(None)
):
    """Creates a journey with the given specifications.

    This requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor("weak")

        # we need to read these to produce the result anyway, so this is not
        # putting an extra request in the happy path. Since we're using uids
        # this can't meaningfully race, as if they get deleted before the insert
        # the insert will fail and we will simply provide less context than we
        # might otherwise
        response = await cursor.execute(
            """
            WITH dummy(id) AS (VALUES (1))
            SELECT
                content_files.uid,
                image_files.uid,
                journey_subcategories.internal_name,
                journey_subcategories.external_name,
                instructors.name,
                ins_picture_image_files.uid,
                instructors.created_at,
                blurred_image_files.uid,
                darkened_image_files.uid,
                journey_subcategories.bias,
                instructors.bias,
                variation_journeys.uid,
                variation_journeys.variation_of_journey_id,
                variation_journeys.deleted_at
            FROM dummy
            LEFT OUTER JOIN content_files ON (
                EXISTS (
                    SELECT 1 FROM journey_audio_contents
                    WHERE journey_audio_contents.uid = ?
                      AND journey_audio_contents.content_file_id = content_files.id
                )
            )
            LEFT OUTER JOIN image_files ON (
                EXISTS (
                    SELECT 1 FROM journey_background_images
                    WHERE journey_background_images.uid = ?
                      AND journey_background_images.image_file_id = image_files.id
                )
            )
            LEFT OUTER JOIN image_files AS blurred_image_files ON (
                EXISTS (
                    SELECT 1 FROM journey_background_images
                    WHERE journey_background_images.uid = ?
                      AND journey_background_images.blurred_image_file_id = blurred_image_files.id
                )
            )
            LEFT OUTER JOIN image_files AS darkened_image_files ON (
                EXISTS (
                    SELECT 1 FROM journey_background_images
                    WHERE journey_background_images.uid = ?
                        AND journey_background_images.darkened_image_file_id = darkened_image_files.id
                )
            )
            LEFT OUTER JOIN journey_subcategories ON (
                journey_subcategories.uid = ?
            )
            LEFT OUTER JOIN instructors ON (
                instructors.uid = ?
                AND instructors.deleted_at IS NULL
            )
            LEFT OUTER JOIN image_files AS ins_picture_image_files ON (
                ins_picture_image_files.id = instructors.picture_image_file_id
            )
            LEFT OUTER JOIN journeys AS variation_journeys ON (
                variation_journeys.uid = ?
            )
            """,
            (
                args.journey_audio_content_uid,
                args.journey_background_image_uid,
                args.journey_background_image_uid,
                args.journey_background_image_uid,
                args.journey_subcategory_uid,
                args.instructor_uid,
                args.variation_of_journey_uid,
            ),
        )

        assert response.results is not None, "expected results for query"
        assert len(response.results) == 1, "expected exactly one row"

        content_file_uid = typing_cast(Optional[str], response.results[0][0])
        image_file_uid = typing_cast(Optional[str], response.results[0][1])
        subcategory_internal_name = typing_cast(Optional[str], response.results[0][2])
        subcategory_external_name = typing_cast(Optional[str], response.results[0][3])
        instructor_name = typing_cast(Optional[str], response.results[0][4])
        instructor_picture_image_file_uid = typing_cast(
            Optional[str], response.results[0][5]
        )
        instructor_created_at = typing_cast(Optional[float], response.results[0][6])
        blurred_image_file_uid = typing_cast(Optional[str], response.results[0][7])
        darkened_image_file_uid = typing_cast(Optional[str], response.results[0][8])
        subcategory_bias = typing_cast(Optional[float], response.results[0][9])
        instructor_bias = typing_cast(Optional[float], response.results[0][10])
        variation_uid = typing_cast(Optional[str], response.results[0][11])
        variation_variation_id = typing_cast(Optional[int], response.results[0][12])
        variation_deleted_at = typing_cast(Optional[float], response.results[0][13])

        if content_file_uid is None:
            return Response(
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="journey_audio_content_not_found",
                    message="No journey audio content with that uid exists, it may have been deleted",
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=404,
            )

        if (
            image_file_uid is None
            or blurred_image_file_uid is None
            or darkened_image_file_uid is None
        ):
            return Response(
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="journey_background_image_not_found",
                    message="No journey background image with that uid exists, it may have been deleted",
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=404,
            )

        if subcategory_internal_name is None:
            return Response(
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="journey_subcategory_not_found",
                    message="No journey subcategory with that uid exists, it may have been deleted",
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=404,
            )

        if instructor_name is None:
            return Response(
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="instructor_not_found",
                    message="No instructor with that uid exists, it may have been deleted",
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=404,
            )

        if variation_uid is None and args.variation_of_journey_uid is not None:
            return Response(
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="variation_journey_not_found",
                    message="The variation_of_journey does not exist",
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=404,
            )

        if variation_uid is not None and variation_variation_id is not None:
            return Response(
                content=StandardErrorResponse[ERROR_409_TYPES](
                    type="variation_journey_is_variation",
                    message="The variation_of_journey is a variation itself",
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=409,
            )

        if variation_uid is not None and variation_deleted_at is not None:
            return Response(
                content=StandardErrorResponse[ERROR_409_TYPES](
                    type="variation_journey_deleted",
                    message="The variation_of_journey is deleted",
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=409,
            )

        assert subcategory_external_name is not None
        assert subcategory_bias is not None
        assert instructor_picture_image_file_uid is not None
        assert instructor_created_at is not None
        assert instructor_bias is not None

        interactive_prompt_uid = f"oseh_ip_{secrets.token_urlsafe(16)}"
        uid = f"oseh_j_{secrets.token_urlsafe(16)}"
        now = time.time()
        response = await cursor.executemany3(
            (
                (
                    """
                    INSERT INTO interactive_prompts (
                        uid,
                        prompt,
                        duration_seconds,
                        created_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        interactive_prompt_uid,
                        args.prompt.model_dump_json(),
                        args.lobby_duration_seconds,
                        now,
                    ),
                ),
                (
                    f"""
                    INSERT INTO journeys (
                        uid,
                        audio_content_file_id,
                        background_image_file_id,
                        blurred_background_image_file_id,
                        darkened_background_image_file_id,
                        instructor_id,
                        title,
                        description,
                        journey_subcategory_id,
                        interactive_prompt_id,
                        created_at,
                        variation_of_journey_id
                    )
                    SELECT
                        ?,
                        journey_audio_contents.content_file_id,
                        journey_background_images.image_file_id,
                        journey_background_images.blurred_image_file_id,
                        journey_background_images.darkened_image_file_id,
                        instructors.id,
                        ?, ?,
                        journey_subcategories.id,
                        interactive_prompts.id, 
                        ?,
                        {'NULL' if args.variation_of_journey_uid is None else 'variation_journeys.id'}
                    FROM journey_audio_contents, journey_background_images, instructors, journey_subcategories, interactive_prompts{'' if args.variation_of_journey_uid is None else ', journeys AS variation_journeys'}
                    WHERE
                        journey_audio_contents.uid = ?
                        AND journey_background_images.uid = ?
                        AND instructors.uid = ?
                        AND instructors.deleted_at IS NULL
                        AND journey_subcategories.uid = ?
                        AND interactive_prompts.uid = ?
                        {'' if args.variation_of_journey_uid is None else 'AND variation_journeys.uid = ? AND variation_journeys.variation_of_journey_id IS NULL AND variation_journeys.deleted_at IS NULL'}
                    """,
                    (
                        uid,
                        args.title,
                        args.description,
                        now,
                        args.journey_audio_content_uid,
                        args.journey_background_image_uid,
                        args.instructor_uid,
                        args.journey_subcategory_uid,
                        interactive_prompt_uid,
                        *(
                            tuple()
                            if args.variation_of_journey_uid is None
                            else (args.variation_of_journey_uid,)
                        ),
                    ),
                ),
            )
        )

        if response[1].rows_affected is None or response[1].rows_affected < 1:
            if response[0].rows_affected is not None and response[0].rows_affected > 0:
                await cursor.execute(
                    """
                    DELETE FROM interactive_prompts
                    WHERE uid = ?
                    """,
                    (interactive_prompt_uid,),
                )
            return Response(
                content=StandardErrorResponse[ERROR_503_TYPES](
                    type="raced",
                    message=(
                        "Some of the resources referenced were deleted before the journey "
                        "could be created, but the specific one could not be determined. "
                        "Retry for a more specific error message, or contact support if the "
                        "problem persists."
                    ),
                ).model_dump_json(),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Retry-After": "3",
                },
                status_code=503,
            )

        await assign_slug_from_title(itgs, journey_uid=uid, title=args.title)
        await journeys.lib.stats.on_journey_created(itgs, created_at=now)
        jobs = await itgs.jobs()
        await jobs.enqueue("runners.refresh_journey_emotions", journey_uid=uid)
        await jobs.enqueue("runners.process_journey_video_sample", journey_uid=uid)
        await jobs.enqueue("runners.process_journey_video", journey_uid=uid)
        await jobs.enqueue("runners.process_journey_share_image", journey_uid=uid)
        return Response(
            content=CreateJourneyResponse(
                uid=uid,
                audio_content=ContentFileRef(
                    uid=content_file_uid,
                    jwt=await content_files.auth.create_jwt(itgs, content_file_uid),
                ),
                background_image=ImageFileRef(
                    uid=image_file_uid,
                    jwt=await image_files.auth.create_jwt(itgs, image_file_uid),
                ),
                blurred_background_image=ImageFileRef(
                    uid=blurred_image_file_uid,
                    jwt=await image_files.auth.create_jwt(itgs, blurred_image_file_uid),
                ),
                darkened_background_image=ImageFileRef(
                    uid=darkened_image_file_uid,
                    jwt=await image_files.auth.create_jwt(
                        itgs, darkened_image_file_uid
                    ),
                ),
                subcategory=JourneySubcategory(
                    uid=args.journey_subcategory_uid,
                    internal_name=subcategory_internal_name,
                    external_name=subcategory_external_name,
                    bias=subcategory_bias,
                ),
                instructor=Instructor(
                    uid=args.instructor_uid,
                    name=instructor_name,
                    bias=instructor_bias,
                    picture=ImageFileRef(
                        uid=instructor_picture_image_file_uid,
                        jwt=await image_files.auth.create_jwt(
                            itgs, instructor_picture_image_file_uid
                        ),
                    ),
                    created_at=instructor_created_at,
                    deleted_at=None,
                ),
                title=args.title,
                description=args.description,
                prompt=args.prompt,
                lobby_duration_seconds=args.lobby_duration_seconds,
                created_at=now,
                sample=None,
                video=None,
                variation_of_journey_uid=args.variation_of_journey_uid,
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=201,
        )
