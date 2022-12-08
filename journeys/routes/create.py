import secrets
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, constr, validator
from typing import List, Optional, Literal, Union
from auth import auth_admin
from image_files.models import ImageFileRef
import image_files.auth
from content_files.models import ContentFileRef
import content_files.auth
from instructors.routes.read import Instructor
from itgs import Itgs
from journeys.subcategories.routes.read import JourneySubcategory
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
import journeys.lib.stats
import time


router = APIRouter()


class NumericPrompt(BaseModel):
    """E.g., What's your mood? 1-10"""

    style: Literal["numeric"] = Field(description="The prompt style")
    text: constr(strip_whitespace=True, min_length=1, max_length=45) = Field(
        description="The text to display to the user before they answer"
    )
    min: int = Field(description="The minimum value, inclusive")
    max: int = Field(description="The maximum value, inclusive")
    step: Literal[1] = Field(description="The step size between values")

    @validator("max")
    def max_must_be_gte_than_min(cls, v, values):
        if v < values["min"]:
            raise ValueError("max must be at least min")
        return v

    @validator("step")
    def at_most_10_options(cls, v, values):
        _min = values["min"]
        _max = values["max"]
        step = v

        if (_max - _min) // step > 10:
            raise ValueError("at most 10 options")

        return v

    class Config:
        schema_extra = {
            "example": {
                "style": "numeric",
                "text": "What's your mood?",
                "min": 1,
                "max": 10,
                "step": 1,
            }
        }


class PressPrompt(BaseModel):
    """E.g., press when you like it"""

    style: Literal["press"] = Field(description="The prompt style")
    text: constr(strip_whitespace=True, min_length=1, max_length=45) = Field(
        description="The text to display to the user before they answer"
    )


class ColorPrompt(BaseModel):
    """E.g., what color is this song?"""

    style: Literal["color"] = Field(description="The prompt style")
    text: constr(strip_whitespace=True, min_length=1, max_length=45) = Field(
        description="The text to display to the user before they answer"
    )
    colors: List[str] = Field(
        description="The colors to choose from", min_length=2, max_length=8
    )

    @validator("colors")
    def colors_must_be_hex(cls, v: List[str]):
        for color in v:
            if not color.startswith("#"):
                raise ValueError("colors must be hex codes starting with #")
            if len(color) != 7:
                raise ValueError("colors must be 6 digit hex codes starting with #")
            if not all(c in "0123456789abcdefABCDEF" for c in color[1:]):
                raise ValueError("colors must be hex codes starting with #")
        return [color.upper() for color in v]


class WordPrompt(BaseModel):
    """e.g. what are you feeling?"""

    style: Literal["word"] = Field(description="The prompt style")
    text: constr(strip_whitespace=True, min_length=1, max_length=45) = Field(
        description="The text to display to the user before they answer"
    )
    options: List[constr(min_length=1, max_length=45, strip_whitespace=True)] = Field(
        description="The options to choose from", min_length=2, max_length=8
    )


Prompt = Union[NumericPrompt, PressPrompt, ColorPrompt, WordPrompt]


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
    title: constr(strip_whitespace=True, min_length=1, max_length=48) = Field(
        description="The display title"
    )
    description: constr(strip_whitespace=True, min_length=1, max_length=255) = Field(
        description="The display description"
    )
    prompt: Prompt = Field(
        description="The prompt style, text, and options to display to the user"
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


ERROR_404_TYPES = Literal[
    "journey_audio_content_not_found",
    "journey_background_image_not_found",
    "journey_subcategory_not_found",
    "instructor_not_found",
]

ERROR_503_TYPES = Literal["raced"]


@router.post(
    "/",
    status_code=201,
    response_model=CreateJourneyResponse,
    responses=STANDARD_ERRORS_BY_CODE,
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
                instructors.created_at
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
            LEFT OUTER JOIN instructors ON (
                instructors.uid = ?
                AND instructors.deleted_at IS NULL
            )
            LEFT OUTER JOIN image_files AS ins_picture_image_files ON (
                ins_picture_image_files.id = instructors.picture_image_file_id
            )
            """,
            (
                args.journey_audio_content_uid,
                args.journey_background_image_uid,
                args.instructor_uid,
            ),
        )

        assert len(response.results) == 1, "expected exactly one row"

        content_file_uid: Optional[str] = response.results[0][0]
        image_file_uid: Optional[str] = response.results[0][1]
        subcategory_internal_name: Optional[str] = response.results[0][2]
        subcategory_external_name: Optional[str] = response.results[0][3]
        instructor_name: Optional[str] = response.results[0][4]
        instructor_picture_image_file_uid: Optional[str] = response.results[0][5]
        instructor_created_at: Optional[float] = response.results[0][6]

        if content_file_uid is None:
            return Response(
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="journey_audio_content_not_found",
                    message="No journey audio content with that uid exists, it may have been deleted",
                ).json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=404,
            )

        if image_file_uid is None:
            return Response(
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="journey_background_image_not_found",
                    message="No journey background image with that uid exists, it may have been deleted",
                ).json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=404,
            )

        if subcategory_internal_name is None:
            return Response(
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="journey_subcategory_not_found",
                    message="No journey subcategory with that uid exists, it may have been deleted",
                ).json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=404,
            )

        if instructor_name is None:
            return Response(
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="instructor_not_found",
                    message="No instructor with that uid exists, it may have been deleted",
                ).json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=404,
            )

        assert subcategory_external_name is not None
        assert instructor_picture_image_file_uid is not None
        assert instructor_created_at is not None

        uid = f"oseh_j_{secrets.token_urlsafe(16)}"
        now = time.time()
        response = await cursor.execute(
            """
            INSERT INTO journeys (
                uid,
                audio_content_file_id,
                background_image_file_id,
                instructor_id,
                title,
                description,
                journey_subcategory_id,
                prompt,
                created_at
            )
            SELECT
                ?,
                journey_audio_contents.content_file_id,
                journey_background_images.image_file_id,
                instructors.id,
                ?, ?,
                journey_subcategories.id,
                ?, ?
            FROM journey_audio_contents, journey_background_images, instructors, journey_subcategories
            WHERE
                journey_audio_contents.uid = ?
                AND journey_background_images.uid = ?
                AND instructors.uid = ?
                AND instructors.deleted_at IS NULL
                AND journey_subcategories.uid = ?
            """,
            (
                uid,
                args.title,
                args.description,
                args.prompt.json(),
                now,
                args.journey_audio_content_uid,
                args.journey_background_image_uid,
                args.instructor_uid,
                args.journey_subcategory_uid,
            ),
        )

        if response.rows_affected is None or response.rows_affected < 1:
            return Response(
                content=StandardErrorResponse[ERROR_503_TYPES](
                    type="raced",
                    message=(
                        "Some of the resources referenced were deleted before the journey "
                        "could be created, but the specific one could not be determined. "
                        "Retry for a more specific error message, or contact support if the "
                        "problem persists."
                    ),
                ).json(),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Retry-After": "3",
                },
                status_code=503,
            )

        await journeys.lib.stats.on_journey_created(itgs, created_at=now)
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
                subcategory=JourneySubcategory(
                    uid=args.journey_subcategory_uid,
                    internal_name=subcategory_internal_name,
                    external_name=subcategory_external_name,
                ),
                instructor=Instructor(
                    uid=args.instructor_uid,
                    name=instructor_name,
                    picture=ImageFileRef(
                        uid=instructor_picture_image_file_uid,
                        jwt=image_files.auth.create_jwt(
                            itgs, instructor_picture_image_file_uid
                        ),
                    ),
                    created_at=instructor_created_at,
                    deleted_at=None,
                ),
                title=args.title,
                description=args.description,
                prompt=args.prompt,
                created_at=now,
            ).json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=201,
        )
