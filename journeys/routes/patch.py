import json
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, constr
from typing import Any, List, Optional, Literal
from auth import auth_admin
from content_files.models import ContentFileRef
import content_files.auth as content_files_auth
from image_files.models import ImageFileRef
import image_files.auth as image_files_auth
from instructors.routes.read import Instructor
from journeys.lib.read_one_external import evict_external_journey
from journeys.routes.create import Prompt, CreateJourneyResponse
from journeys.subcategories.routes.read import JourneySubcategory
from journeys.events.helper import purge_journey_meta
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from itgs import Itgs
from pypika import Query, Table, Parameter
from pypika.queries import QueryBuilder
from pypika.terms import ExistsCriterion, Term
from db.utils import ParenthisizeCriterion
from daily_events.lib.read_one_external import evict_external_daily_event


router = APIRouter()


class PatchJourneyRequest(BaseModel):
    journey_audio_content_uid: Optional[str] = Field(
        None,
        description=(
            "The UID of the journey audio content to be used for this journey. "
            "May be null to keep the audio content as is."
        ),
    )
    journey_background_image_uid: Optional[str] = Field(
        None,
        description=(
            "The UID of the journey background image to be used for this journey. "
            "May be null to keep the background image as is."
        ),
    )
    journey_subcategory_uid: Optional[str] = Field(
        None,
        description=(
            "The UID of the journey subcategory this journey belongs to. May be "
            "null to keep the subcategory as is."
        ),
    )
    instructor_uid: Optional[str] = Field(
        None,
        description=(
            "The UID of the instructor we are crediting for this journey. May be "
            "null to keep the instructor as is."
        ),
    )
    title: Optional[constr(strip_whitespace=True, min_length=1, max_length=48)] = Field(
        None, description="The display title, may be null to keep the title as is."
    )
    description: Optional[
        constr(strip_whitespace=True, min_length=1, max_length=255)
    ] = Field(
        None,
        description="The display description, may be null to keep the description as is.",
    )
    prompt: Optional[Prompt] = Field(
        None,
        description="The prompt to be used for this journey, may be null to keep the prompt as is.",
    )


PatchJourneyResponse = CreateJourneyResponse


ERROR_400_TYPES = Literal[
    "nothing_to_patch",
]

ERROR_404_TYPES = Literal[
    "journey_not_found",
    "journey_audio_content_not_found",
    "journey_background_image_not_found",
    "journey_subcategory_not_found",
    "instructor_not_found",
]

ERROR_503_TYPES = Literal["raced"]


@router.patch(
    "/{uid}",
    status_code=200,
    response_model=PatchJourneyResponse,
    responses={
        "400": {
            "description": "The request did not indicate any requested changes",
            "model": StandardErrorResponse[ERROR_400_TYPES],
        },
        "404": {
            "description": "A referenced resource was not found",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def patch_journey(
    uid: str, args: PatchJourneyRequest, authorization: Optional[str] = Header(None)
):
    """Patches the journey, modifying it where specified and leaving the other
    fields as-is. A patch style is used for journeys since there is a
    discrepancy between how some fields are specified and how they are stored:
    in particular, for the audio content, it must be specified as a uid in
    `journey_audio_contents`, which ensures it was exported properly, but stored
    as a bare `content_files` reference. This allows us to, for example, clear
    `journey_audio_contents` if we add a new export, ensuring they aren't used
    in any _new_ journeys, without affecting existing journeys.

    This requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        if (
            args.journey_audio_content_uid is None
            and args.journey_background_image_uid is None
            and args.journey_subcategory_uid is None
            and args.instructor_uid is None
            and args.title is None
            and args.description is None
            and args.prompt is None
        ):
            return Response(
                content=StandardErrorResponse[ERROR_400_TYPES](
                    type="nothing_to_patch",
                    message="No fields were specified to be patched",
                ).json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=400,
            )

        conn = await itgs.conn()
        cursor = conn.cursor("weak")

        # we need to get the current values for the fields we're not updating,
        # and, for fields which will be transformed, we need to get the
        # transformed values

        journeys = Table("journeys")
        journey_audio_contents = Table("journey_audio_contents")
        journey_background_images = Table("journey_background_images")
        journey_subcategories = Table("journey_subcategories")
        content_files = Table("content_files")
        image_files = Table("image_files")
        blurred_image_files = image_files.as_("blurred_image_files")
        instructors = Table("instructors")
        instructor_pictures = image_files.as_("instructor_pictures")
        dummy = Table("dummy")

        query_prefix = "WITH dummy(id) AS (VALUES (1)) "
        query: QueryBuilder = (
            Query.from_(dummy)
            .select(
                ParenthisizeCriterion(journeys.uid.isnotnull()).as_("jexists"),
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
                journeys.created_at,
                journeys.title,
                journeys.description,
                journeys.prompt,
                blurred_image_files.uid,
            )
            .left_join(journeys)
            .on((journeys.uid == Parameter("?")) & journeys.deleted_at.isnull())
        )
        qargs = [uid]

        if args.journey_audio_content_uid is None:
            query = query.join(content_files).on(
                content_files.id == journeys.audio_content_file_id
            )
        else:
            query = query.left_outer_join(content_files).on(
                ExistsCriterion(
                    Query.from_(journey_audio_contents)
                    .select(1)
                    .where(journey_audio_contents.content_file_id == content_files.id)
                    .where(journey_audio_contents.uid == Parameter("?"))
                )
            )
            qargs.append(args.journey_audio_content_uid)

        if args.journey_background_image_uid is None:
            query = (
                query.join(image_files)
                .on(image_files.id == journeys.background_image_file_id)
                .join(blurred_image_files)
                .on(blurred_image_files.id == journeys.blurred_background_image_file_id)
            )
        else:
            query = (
                query.left_outer_join(image_files)
                .on(
                    ExistsCriterion(
                        Query.from_(journey_background_images)
                        .select(1)
                        .where(
                            journey_background_images.image_file_id == image_files.id
                        )
                        .where(journey_background_images.uid == Parameter("?"))
                    )
                )
                .left_outer_join(blurred_image_files)
                .on(
                    ExistsCriterion(
                        Query.from_(journey_background_images)
                        .select(1)
                        .where(
                            journey_background_images.blurred_image_file_id
                            == blurred_image_files.id
                        )
                        .where(journey_background_images.uid == Parameter("?"))
                    )
                )
            )
            qargs.append(args.journey_background_image_uid)

        if args.journey_subcategory_uid is None:
            query = query.join(journey_subcategories).on(
                journey_subcategories.id == journeys.journey_subcategory_id
            )
        else:
            query = query.left_outer_join(journey_subcategories).on(
                journey_subcategories.uid == Parameter("?")
            )
            qargs.append(args.journey_subcategory_uid)

        if args.instructor_uid is None:
            query = (
                query.inner_join(instructors)
                .on(instructors.id == journeys.instructor_id)
                .left_outer_join(instructor_pictures)
                .on(instructor_pictures.id == instructors.picture_image_file_id)
            )
        else:
            query = (
                query.left_outer_join(instructors)
                .on(
                    (instructors.uid == Parameter("?"))
                    & instructors.deleted_at.isnull()
                )
                .left_outer_join(instructor_pictures)
                .on(instructor_pictures.id == instructors.picture_image_file_id)
            )
            qargs.append(args.instructor_uid)

        response = await cursor.execute(query_prefix + query.get_sql(), qargs)
        assert len(response.results) == 1

        journey_exists: bool = response.results[0][0]
        content_file_uid: Optional[str] = response.results[0][1]
        image_file_uid: Optional[str] = response.results[0][2]
        journey_subcategory_uid: Optional[str] = response.results[0][3]
        journey_subcategory_internal_name: Optional[str] = response.results[0][4]
        journey_subcategory_external_name: Optional[str] = response.results[0][5]
        instructor_uid: Optional[str] = response.results[0][6]
        instructor_name: Optional[str] = response.results[0][7]
        instructor_picture_file_uid: Optional[str] = response.results[0][8]
        instructor_created_at: Optional[float] = response.results[0][9]
        instructor_deleted_at: Optional[float] = response.results[0][10]
        journey_created_at: Optional[float] = response.results[0][11]
        journey_title: Optional[str] = response.results[0][12]
        journey_description: Optional[str] = response.results[0][13]
        journey_prompt: Optional[str] = response.results[0][14]
        blurred_image_file_uid: Optional[str] = response.results[0][15]

        if not journey_exists:
            return Response(
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="journey_not_found",
                    message="The journey with the specified uid was not found.",
                ).json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=404,
            )

        if content_file_uid is None:
            return Response(
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="journey_audio_content_not_found",
                    message="The journey audio content with the specified uid was not found.",
                ).json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=404,
            )

        if image_file_uid is None or blurred_image_file_uid is None:
            return Response(
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="journey_background_image_not_found",
                    message="The journey background image with the specified uid was not found.",
                ).json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=404,
            )

        if journey_subcategory_uid is None:
            return Response(
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="journey_subcategory_not_found",
                    message="The journey subcategory with the specified uid was not found.",
                ).json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=404,
            )

        if instructor_uid is None:
            return Response(
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="instructor_not_found",
                    message="The instructor with the specified uid was not found.",
                ).json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=404,
            )

        assert journey_subcategory_internal_name is not None
        assert journey_subcategory_external_name is not None
        assert instructor_name is not None
        assert instructor_created_at is not None
        assert journey_created_at is not None
        assert journey_title is not None
        assert journey_description is not None
        assert journey_prompt is not None

        update_and_set_query: QueryBuilder = Query.update(journeys)
        from_query: QueryBuilder = Query.select(1)
        del qargs
        set_qargs = []
        join_qargs = []
        where_qargs = []

        is_first_join = True

        def join_on(table: Table, on: Term, qargs: List[Any]) -> QueryBuilder:
            nonlocal is_first_join

            if is_first_join:
                is_first_join = False
                where_qargs.extend(qargs)
                return from_query.from_(table).where(on)

            join_qargs.extend(qargs)
            return from_query.join(table).on(on)

        if args.journey_audio_content_uid is not None:
            update_and_set_query = update_and_set_query.set(
                journeys.audio_content_file_id, content_files.id
            )
            from_query = join_on(
                content_files,
                ExistsCriterion(
                    Query.from_(journey_audio_contents)
                    .select(1)
                    .where(journey_audio_contents.content_file_id == content_files.id)
                    .where(journey_audio_contents.uid == Parameter("?"))
                ),
                [args.journey_audio_content_uid],
            )

        if args.journey_background_image_uid is not None:
            update_and_set_query = update_and_set_query.set(
                journeys.background_image_file_id, image_files.id
            ).set(journeys.blurred_background_image_file_id, blurred_image_files.id)
            from_query = join_on(
                image_files,
                ExistsCriterion(
                    Query.from_(journey_background_images)
                    .select(1)
                    .where(journey_background_images.image_file_id == image_files.id)
                    .where(journey_background_images.uid == Parameter("?"))
                ),
                [args.journey_background_image_uid],
            )
            from_query = join_on(
                blurred_image_files,
                ExistsCriterion(
                    Query.from_(journey_background_images)
                    .select(1)
                    .where(
                        journey_background_images.blurred_image_file_id
                        == blurred_image_files.id
                    )
                    .where(journey_background_images.uid == Parameter("?"))
                ),
                [args.journey_background_image_uid],
            )

        if args.journey_subcategory_uid is not None:
            update_and_set_query = update_and_set_query.set(
                journeys.journey_subcategory_id, journey_subcategories.id
            )
            from_query = join_on(
                journey_subcategories,
                journey_subcategories.uid == Parameter("?"),
                [args.journey_subcategory_uid],
            )

        if args.instructor_uid is not None:
            update_and_set_query = update_and_set_query.set(
                journeys.instructor_id, instructors.id
            )
            from_query = join_on(
                instructors, instructors.uid == Parameter("?"), [args.instructor_uid]
            )

        if args.title is not None:
            update_and_set_query = update_and_set_query.set(
                journeys.title, Parameter("?")
            )
            set_qargs.append(args.title)

        if args.description is not None:
            update_and_set_query = update_and_set_query.set(
                journeys.description, Parameter("?")
            )
            set_qargs.append(args.description)

        if args.prompt is not None:
            update_and_set_query = update_and_set_query.set(
                journeys.prompt, Parameter("?")
            )
            set_qargs.append(args.prompt.json())

        from_query = from_query.where(journeys.uid == Parameter("?")).where(
            journeys.deleted_at.isnull()
        )
        where_qargs.append(uid)

        query = (
            update_and_set_query._update_sql(with_namespace=True)
            + update_and_set_query._set_sql(with_namespace=True)
            + " "
            + from_query.get_sql().lstrip("SELECT 1 ")
        )

        response = await cursor.execute(query, set_qargs + join_qargs + where_qargs)
        if response.rows_affected is None or response.rows_affected < 1:
            return Response(
                content=StandardErrorResponse[ERROR_503_TYPES](
                    type="raced",
                    message="The journey was updated by another request.",
                ).json(),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Retry-After": "1",
                },
                status_code=503,
            )

        # this select definitely races, but fixing it would require a lot of
        # work
        response = await cursor.execute(
            """
            SELECT
                uid
            FROM daily_events
            WHERE
                EXISTS (
                    SELECT 1 FROM daily_event_journeys
                    WHERE daily_event_journeys.daily_event_id = daily_events.id
                      AND EXISTS (
                        SELECT 1 FROM journeys
                        WHERE journeys.id = daily_event_journeys.journey_id
                          AND journeys.uid = ?
                      )
                )
            """,
            (uid,),
        )
        daily_event_uid: Optional[str] = (
            response.results[0][0] if response.results else None
        )
        if daily_event_uid:
            await evict_external_daily_event(itgs, uid=daily_event_uid)

        await purge_journey_meta(itgs, uid)
        await evict_external_journey(itgs, uid=uid)
        return Response(
            content=PatchJourneyResponse(
                uid=uid,
                audio_content=ContentFileRef(
                    uid=content_file_uid,
                    jwt=await content_files_auth.create_jwt(itgs, content_file_uid),
                ),
                background_image=ImageFileRef(
                    uid=image_file_uid,
                    jwt=await image_files_auth.create_jwt(itgs, image_file_uid),
                ),
                blurred_background_image=ImageFileRef(
                    uid=blurred_image_file_uid,
                    jwt=await image_files_auth.create_jwt(itgs, blurred_image_file_uid),
                ),
                subcategory=JourneySubcategory(
                    uid=journey_subcategory_uid,
                    internal_name=journey_subcategory_internal_name,
                    external_name=journey_subcategory_external_name,
                ),
                instructor=Instructor(
                    uid=instructor_uid,
                    name=instructor_name,
                    picture=(
                        ImageFileRef(
                            uid=instructor_picture_file_uid,
                            jwt=await image_files_auth.create_jwt(
                                itgs, instructor_picture_file_uid
                            ),
                        )
                        if instructor_picture_file_uid is not None
                        else None
                    ),
                    created_at=instructor_created_at,
                    deleted_at=instructor_deleted_at,
                ),
                title=args.title if args.title is not None else journey_title,
                description=args.description
                if args.description is not None
                else journey_description,
                prompt=args.prompt
                if args.prompt is not None
                else json.loads(journey_prompt),
                created_at=journey_created_at,
            ).json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=200,
        )
