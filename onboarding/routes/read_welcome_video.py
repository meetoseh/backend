import random
from typing import Annotated, List, Optional, Literal, Tuple, cast
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, TypeAdapter
from content_files.models import ContentFileRef
from content_files.auth import create_jwt as create_content_file_jwt
from error_middleware import handle_error, handle_warning
from lib.shared.extract_language_code import extract_language_code, extract_locale
from transcripts.models.transcript_ref import TranscriptRef
from transcripts.auth import create_jwt as create_transcript_jwt
from image_files.models import ImageFileRef
from image_files.auth import create_jwt as create_image_file_jwt
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from auth import auth_any
from itgs import Itgs
from lib.gender.by_user import Gender, get_gender_by_user
import gzip

router = APIRouter()


class ReadOnboardingVideoResponse(BaseModel):
    onboarding_video_uid: str = Field(
        description="The UID of the onboarding_video association"
    )
    video: ContentFileRef = Field(description="The onboarding video for the user")
    thumbnail: ImageFileRef = Field(
        description="The thumbnail / cover image for the video"
    )
    transcript: Optional[TranscriptRef] = Field(
        description="The transcript for the video"
    )


class OnboardingVideoOption(BaseModel):
    onboarding_video_uid: str = Field(description="The UID of the onboarding_video row")
    content_file_uid: str = Field(description="The content file UID")
    thumbnail_uid: str = Field(description="The thumbnail UID")
    transcript_uid: Optional[str] = Field(
        description="The transcript UID, if it exists"
    )


options_adapter: TypeAdapter[List[OnboardingVideoOption]] = TypeAdapter(
    List[OnboardingVideoOption]
)


ERROR_500_TYPES = Literal["server-error"]
ERROR_NOT_FOUND_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_500_TYPES](
        type="server-error",
        message="Unable to determine an onboarding video for the user",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=500,
)


@router.get(
    "/welcome-video",
    response_model=ReadOnboardingVideoResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_welcome_video(
    accept_language: Annotated[Optional[str], Header()] = None,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Fetches the onboarding video for the authorized user in the given
    language.

    Requires standard authorization.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        locale_for_gender = extract_locale(accept_language, None)
        gender_with_source = await get_gender_by_user(
            itgs, sub=auth_result.result.sub, locale=locale_for_gender
        )

        language = extract_language_code(accept_language, "en")
        try:
            options = await _get_options(
                itgs, gender=gender_with_source.gender, language=language
            )
            assert options
        except AssertionError as e:
            await handle_error(e)
            return ERROR_NOT_FOUND_RESPONSE

        choice = random.choice(options)
        if choice.transcript_uid is None:
            await handle_warning(
                f"{__name__}:no_transcript",
                f"serving onboarding video without transcript for `{auth_result.result.sub}`: `{choice.content_file_uid}`",
            )

        return Response(
            content=ReadOnboardingVideoResponse.__pydantic_serializer__.to_json(
                ReadOnboardingVideoResponse(
                    onboarding_video_uid=choice.onboarding_video_uid,
                    video=ContentFileRef(
                        uid=choice.content_file_uid,
                        jwt=await create_content_file_jwt(
                            itgs, choice.content_file_uid
                        ),
                    ),
                    thumbnail=ImageFileRef(
                        uid=choice.thumbnail_uid,
                        jwt=await create_image_file_jwt(itgs, choice.thumbnail_uid),
                    ),
                    transcript=(
                        None
                        if choice.transcript_uid is None
                        else TranscriptRef(
                            uid=choice.transcript_uid,
                            jwt=await create_transcript_jwt(
                                itgs, choice.transcript_uid
                            ),
                        )
                    ),
                ),
            ),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=200,
        )


async def _get_options(
    itgs: Itgs, gender: Gender, language: str
) -> List[OnboardingVideoOption]:
    """Fetches the onboarding video options for the combination of gender and
    language.

    If there are any exact matches on the gender and language, returns only
    exact matches. Otherwise, if there are any exact matches on language,
    returns matches for language ignoring gender. Otherwise, retries with
    the language as `en`, and errors if there are no matches.

    Args:
        itgs (Itgs): the integrations to (re)use
        gender ("male", "female", "nonbinary", "unknown"): the gender to
            try to match on. ignored if unknown or nonbinary as they don't
            apply to the masculinity of a voiceover
        language (str): the language to try to match on; should be a 2-letter
            code (e.g., "en")
    """
    cache = await itgs.local_cache()
    raw = cast(Optional[bytes], cache.get(f"onboarding:welcome:{gender}:{language}"))
    if raw is not None:
        return options_adapter.validate_json(gzip.decompress(raw))

    if gender in ("male", "female"):
        if (
            res := await _try_fetch_options_using(
                itgs,
                original_gender=gender,
                original_language=language,
                gender=gender,
                language=language,
            )
        ) is not None:
            return res

    if (
        res := await _try_fetch_options_using(
            itgs,
            original_gender=gender,
            original_language=language,
            gender=None,
            language=language,
        )
    ) is not None:
        return res

    assert language != "en", "no english onboarding welcome videos found"

    res = await _try_fetch_options_using(
        itgs,
        original_gender=gender,
        original_language=language,
        gender=None,
        language="en",
    )
    assert res is not None, "no english onboarding welcome videos found"
    return res


async def _try_fetch_options_using(
    itgs: Itgs,
    /,
    *,
    original_gender: Gender,
    original_language: str,
    gender: Optional[Literal["male", "female"]],
    language: Optional[str],
) -> Optional[List[OnboardingVideoOption]]:
    if original_gender != gender or original_language != language:
        cache = await itgs.local_cache()
        raw = cast(
            Optional[bytes], cache.get(f"onboarding:welcome:{gender}:{language}")
        )
        if raw is not None:
            return options_adapter.validate_json(gzip.decompress(raw))

    conn = await itgs.conn()
    cursor = conn.cursor("none")
    response = await cursor.execute(*_make_query(gender, language))
    if not response.results:
        return None

    parsed = [
        OnboardingVideoOption(
            onboarding_video_uid=r[0],
            content_file_uid=r[1],
            thumbnail_uid=r[2],
            transcript_uid=r[3],
        )
        for r in response.results
    ]

    cache = await itgs.local_cache()
    compressed = gzip.compress(options_adapter.dump_json(parsed), mtime=0)
    cache.set(
        f"onboarding:welcome:{original_gender}:{original_language}",
        compressed,
        expire=1800,
    )
    cache.set(
        f"onboarding:welcome:{gender}:{language}",
        compressed,
        expire=1800,
    )
    return parsed


def _make_query(gender: Optional[Gender], language: Optional[str]) -> Tuple[str, list]:
    query = """
SELECT onboarding_videos.uid, content_files.uid, image_files.uid, transcripts.uid
FROM onboarding_videos, content_files, image_files
LEFT OUTER JOIN content_file_transcripts 
    ON content_file_transcripts.content_file_id = onboarding_videos.video_content_file_id 
LEFT OUTER JOIN transcripts ON transcripts.id = content_file_transcripts.transcript_id
WHERE
    onboarding_videos.video_content_file_id = content_files.id
    AND onboarding_videos.thumbnail_image_file_id = image_files.id
    AND json_extract(onboarding_videos.purpose, '$.type') = 'welcome'
    AND onboarding_videos.active_at IS NOT NULL
    """
    qargs = []
    if gender is not None:
        query += " AND json_extract(onboarding_videos.purpose, '$.voice') = ?"
        qargs.append(gender)

    if language is not None:
        query += "AND json_extract(onboarding_videos.purpose, '$.language') = ?"
        qargs.append(language)

    return query, qargs
