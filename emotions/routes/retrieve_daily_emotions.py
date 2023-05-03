from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import List, Optional
from emotions.lib.emotion_content import get_emotion_content_statistics
from models import STANDARD_ERRORS_BY_CODE, validator
from emotions.routes.read import Emotion
from itgs import Itgs
from auth import auth_any
import random
import numpy as np


router = APIRouter()


class RetrieveDailyEmotionsRequest(BaseModel):
    recently_seen: List[List[str]] = Field(
        default_factory=list,
        description=(
            "The emotion words that were recently presented to "
            "the user, in the order they were presented. Used to "
            "avoid returning the same list the user just shuffled."
        ),
    )

    num_emotions: int = Field(
        description="The number of emotions to return", ge=1, le=12
    )

    @validator("recently_seen")
    def validate_recently_seen(cls, recently_seen):
        if len(recently_seen) > 5:
            raise ValueError("recently_seen cannot have more than 5 items")

        for emotion_list in recently_seen:
            if len(emotion_list) > 12:
                raise ValueError(
                    "recently_seen cannot have a sublist with more than 12 items"
                )
            if len(emotion_list) < 1:
                raise ValueError(
                    "recently_seen cannot have a sublist with less than 1 item"
                )
        return recently_seen


class RetrieveDailyEmotionsResponse(BaseModel):
    items: List[Emotion] = Field(description="The emotions to present to the user")


@router.post(
    "/personalized",
    response_model=RetrieveDailyEmotionsResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def retrieve_daily_emotions(
    args: RetrieveDailyEmotionsRequest,
    authorization: Optional[str] = Header(None),
):
    """Retrieves the emotions that the user should choose from in order to
    get a class using start_related_journey.

    Requires standard authorization.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        stats = await get_emotion_content_statistics(itgs)
        lookup = dict(
            (stat.emotion.word, stat) for stat in stats if stat.num_journeys > 0
        )

        if args.recently_seen:
            exclusion_ends_at = len(args.recently_seen)
            while exclusion_ends_at > 0 and len(lookup) > args.num_emotions:
                exclusion_ends_at -= 1
                to_exclude = list(args.recently_seen[exclusion_ends_at])
                random.shuffle(to_exclude)
                for emotion in to_exclude:
                    if emotion in lookup:
                        del lookup[emotion]
                    if len(lookup) <= args.num_emotions:
                        break

        if len(lookup) <= args.num_emotions:
            selected_emotions = [v.emotion for v in lookup.values()]
            random.shuffle(selected_emotions)
        else:
            options: List[Emotion] = []
            weights: np.ndarray = np.zeros(len(lookup), dtype=np.float64)
            for idx, stat in enumerate(lookup.values()):
                options.append(stat.emotion)
                weights[idx] = float(stat.num_journeys)

            weights /= np.sum(weights)

            selected_emotions = list(
                np.random.choice(
                    options, size=args.num_emotions, replace=False, p=weights
                )
            )

        return Response(
            content=RetrieveDailyEmotionsResponse(items=selected_emotions).json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=200,
        )
