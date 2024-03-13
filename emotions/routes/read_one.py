from fastapi import APIRouter, Header
from fastapi.responses import Response
from typing import Annotated, Optional, Literal, cast

from pydantic import StringConstraints
from emotions.routes.read import Emotion
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from auth import auth_any
from itgs import Itgs


router = APIRouter()

ERROR_404_TYPES = Literal["emotion_not_found"]

ERROR_EMOTION_NOT_FOUND = Response(
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="emotion_not_found",
        message="There is no emotion with that word",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=404,
)


@router.get(
    "/",
    response_model=Emotion,
    responses={
        "404": {
            "description": "There is no emotion with that word",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def read_one_emotion(
    word: Annotated[str, StringConstraints(max_length=64)],
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Reads the complete emotion associated with the emotion with the given
    word. This is primarily intended to assist deep linking.

    Requires standard authorization.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor("none")
        response = await cursor.execute(
            "SELECT antonym FROM emotions WHERE word=?", (word,)
        )
        if not response.results:
            return ERROR_EMOTION_NOT_FOUND
        antonym = cast(str, response.results[0][0])
        return Response(
            content=Emotion.__pydantic_serializer__.to_json(
                Emotion(word=word, antonym=antonym)
            ),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=200,
        )
