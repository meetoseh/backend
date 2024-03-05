from dataclasses import dataclass
from fastapi import APIRouter, Header
from fastapi.responses import Response
from typing import Annotated, List, Literal, Optional, Tuple
from pydantic import BaseModel, Field
from itgs import Itgs
from auth import auth_admin
from lib.shared.redis_hash import RedisHash
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from rqdb.result import ResultItem


router = APIRouter()


class SingleJourneyFeedbackInfo(BaseModel):
    loved: int = Field(description="The number of people who loved the journey")
    liked: int = Field(description="The number of people who liked the journey")
    disliked: int = Field(description="The number of people who disliked the journey")
    hated: int = Field(description="The number of people who hated the journey")


class ReadSingleJourneyFeedbackResponse(BaseModel):
    unique: SingleJourneyFeedbackInfo = Field(description="The unique feedback")
    total: SingleJourneyFeedbackInfo = Field(description="The total feedback")


ERROR_404_TYPES = Literal["not_found"]
NOT_FOUND_RESPONSE = Response(
    status_code=404,
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="not_found", message=("There is no journey with that UID")
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
)

RATING_KEYS: List[bytes] = [b"loved", b"liked", b"disliked", b"hated"]


@router.get(
    "/journey_feedback/{uid}",
    status_code=200,
    response_model=ReadSingleJourneyFeedbackResponse,
    responses={
        "404": {
            "description": "There is no journey with that UID",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def read_single_journey_feedback(
    uid: str, authorization: Annotated[Optional[str], Header()] = None
):
    """Fetches feedback on the journey with the given uid. This can be somewhat
    expensive if it needs to fill the cache for the journey, but once filled it
    will be kept up to date for a while and will be fast to read.

    This endpoint may be slightly inaccurate because filling the cache does not
    happen atomically with the feedback being recorded, meaning that if feedback
    comes in while the cache is being filled it may be counted once, twice, or
    not at all. However, this inaccuracy does not increase once the cache is
    filled.

    Requires standard admin authorization
    """
    async with Itgs() as itgs:
        auth_res = await auth_admin(itgs, authorization)
        if auth_res.result is None:
            return auth_res.error_response

        total_key = f"journeys:feedback:total:{uid}".encode("utf-8")
        unique_key = f"journeys:feedback:unique:{uid}".encode("utf-8")

        redis = await itgs.redis()
        async with redis.pipeline() as pipe:
            pipe.multi()
            await pipe.hgetall(total_key)  # type: ignore
            await pipe.hgetall(unique_key)  # type: ignore
            await pipe.expire(total_key, 3600)
            await pipe.expire(unique_key, 3600)
            total_redis_hash_raw, unique_redis_hash_raw, _, _ = await pipe.execute()

        total_redis_hash = RedisHash(total_redis_hash_raw)
        unique_redis_hash = RedisHash(unique_redis_hash_raw)

        if not any(
            any(h.get_int(k, default=None) is None for k in RATING_KEYS)
            for h in (total_redis_hash, unique_redis_hash)
        ):
            res = ReadSingleJourneyFeedbackResponse(
                unique=SingleJourneyFeedbackInfo(
                    loved=unique_redis_hash.get_int(b"loved"),
                    liked=unique_redis_hash.get_int(b"liked"),
                    disliked=unique_redis_hash.get_int(b"disliked"),
                    hated=unique_redis_hash.get_int(b"hated"),
                ),
                total=SingleJourneyFeedbackInfo(
                    loved=total_redis_hash.get_int(b"loved"),
                    liked=total_redis_hash.get_int(b"liked"),
                    disliked=total_redis_hash.get_int(b"disliked"),
                    hated=total_redis_hash.get_int(b"hated"),
                ),
            )
            return Response(
                status_code=200,
                content=res.__pydantic_serializer__.to_json(res),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Cache-Control": "private, max-age=10, stale-while-revalidate=10, stale-if-error=86400",
                },
            )

        conn = await itgs.conn()
        cursor = conn.cursor("none")

        response = await cursor.executeunified3(
            (
                ("SELECT EXISTS (SELECT 1 FROM journeys WHERE uid = ?)", [uid]),
                _make_query(True, uid),
                _make_query(False, uid),
            )
        )

        assert response.items[0].results
        exists = bool(response.items[0].results[0][0])
        if not exists:
            return NOT_FOUND_RESPONSE

        unique_row = _parse_query_result(response.items[1])
        total_row = _parse_query_result(response.items[2])

        async with redis.pipeline() as pipe:
            pipe.multi()
            await pipe.hset(
                total_key,  # type: ignore
                mapping={  # type: ignore
                    b"loved": str(total_row.loved).encode("utf-8"),
                    b"liked": str(total_row.liked).encode("utf-8"),
                    b"disliked": str(total_row.disliked).encode("utf-8"),
                    b"hated": str(total_row.hated).encode("utf-8"),
                },
            )
            await pipe.hset(
                unique_key,  # type: ignore
                mapping={  # type: ignore
                    b"loved": str(unique_row.loved).encode("utf-8"),
                    b"liked": str(unique_row.liked).encode("utf-8"),
                    b"disliked": str(unique_row.disliked).encode("utf-8"),
                    b"hated": str(unique_row.hated).encode("utf-8"),
                },
            )
            await pipe.expire(total_key, 3600)
            await pipe.expire(unique_key, 3600)
            await pipe.execute()

        res = ReadSingleJourneyFeedbackResponse(
            unique=SingleJourneyFeedbackInfo(
                loved=unique_row.loved,
                liked=unique_row.liked,
                disliked=unique_row.disliked,
                hated=unique_row.hated,
            ),
            total=SingleJourneyFeedbackInfo(
                loved=total_row.loved,
                liked=total_row.liked,
                disliked=total_row.disliked,
                hated=total_row.hated,
            ),
        )

        return Response(
            status_code=200,
            content=res.__pydantic_serializer__.to_json(res),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "private, max-age=10, stale-while-revalidate=10, stale-if-error=86400",
            },
        )


def _make_query(unique: bool, uid: str) -> Tuple[str, list]:
    unique_restriction = ""
    if unique:
        unique_restriction = """
            AND NOT EXISTS (
                SELECT 1 FROM journey_feedback AS jf2
                WHERE
                    journey_feedback.user_id = jf2.user_id
                    AND journey_feedback.journey_id = jf2.journey_id
                    AND (
                        journey_feedback.created_at > jf2.created_at
                        OR (
                            journey_feedback.created_at = jf2.created_at
                            AND journey_feedback.uid > jf2.uid
                        )
                    )
            )
            """

    query = f"""
        WITH all_feedback(version, response, num) AS (
        SELECT
            journey_feedback.version,
            journey_feedback.response,
            COUNT(*)
        FROM journeys, journey_feedback
        WHERE
            journeys.uid = ?
            AND journey_feedback.journey_id = journeys.id
            {unique_restriction}
        GROUP BY journey_feedback.version, journey_feedback.response
        ), feedbackv1(liked, disliked) AS (
        SELECT
            (
                SELECT SUM(num)
                FROM all_feedback
                WHERE
                    version IN (1, 2)
                    AND response = 1
            ),
            (
                SELECT SUM(num)
                FROM all_feedback
                WHERE
                    version IN (1, 2)
                    AND response = 2
            )
        ), feedbackv2(loved, liked, disliked, hated) AS (
        SELECT
            (
                SELECT
                    SUM(num)
                FROM all_feedback
                WHERE
                    version = 3
                    AND response = 1
            ),
            (
                SELECT
                    SUM(num)
                FROM all_feedback
                WHERE
                    version = 3
                    AND response = 2
            ),
            (
                SELECT
                    SUM(num)
                FROM all_feedback
                WHERE
                    version = 3
                    AND response = 3
            ),
            (
                SELECT
                    SUM(num)
                FROM all_feedback
                WHERE
                    version = 3
                    AND response = 4
            )
        )
        SELECT
            COALESCE(feedbackv2.loved, 0) AS loved,
            COALESCE(feedbackv1.liked, 0) + COALESCE(feedbackv2.liked, 0) AS liked,
            COALESCE(feedbackv1.disliked, 0) + COALESCE(feedbackv2.disliked, 0) AS disliked,
            COALESCE(feedbackv2.hated, 0) AS hated
        FROM feedbackv1, feedbackv2
        """

    return (query, [uid])


@dataclass
class _QueryResult:
    loved: int
    liked: int
    disliked: int
    hated: int


def _parse_query_result(item: ResultItem) -> _QueryResult:
    assert item.results
    row = item.results[0]

    res = _QueryResult(
        loved=row[0],
        liked=row[1],
        disliked=row[2],
        hated=row[3],
    )
    assert isinstance(res.loved, int), res
    assert isinstance(res.liked, int), res
    assert isinstance(res.disliked, int), res
    assert isinstance(res.hated, int), res
    return res
