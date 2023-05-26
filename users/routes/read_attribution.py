import asyncio
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Dict, List, Literal, Optional, Tuple
from auth import auth_admin
from journeys.routes.read import Journey, raw_read_journeys
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from itgs import Itgs
from resources.filter_in_item import FilterInItem


router = APIRouter()


class UTMClick(BaseModel):
    utm_source: str = Field()
    utm_medium: Optional[str] = Field(None)
    utm_campaign: Optional[str] = Field(None)
    utm_term: Optional[str] = Field(None)
    utm_content: Optional[str] = Field(None)
    clicked_at: float = Field(description="When they clicked the link")


class JourneyPublicLinkView(BaseModel):
    journey: Journey = Field(description="the journey they took")
    code: str = Field(description="The code of the journey public link")
    clicked_at: float = Field(description="When they clicked the link")


class ReadUserAttributionResponse(BaseModel):
    utms: List[UTMClick] = Field(
        description=(
            "UTMs associated with visitors associated with this user, in order from "
            "most recent to least recent, but only including clicks from before the "
            "user signed up and not including more than 4 clicks in total."
        ),
        max_items=4,
    )

    journey_public_links: List[JourneyPublicLinkView] = Field(
        description=(
            "Journey public links associated with visitors associated with this user, "
            "in order from most recent to least recent, but only including clicks from "
            "before the user signed up and not including more than 4 clicks in total."
        ),
        max_items=4,
    )

    first_seen_at: float = Field(
        description=(
            "The earliest creation time of all the visitors associated with this user, "
            "which will typically be the first time they visited the website, in seconds "
            "since the epoch"
        )
    )


ERROR_404_TYPES = Literal["user_not_found"]
USER_NOT_FOUND_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="user_not_found", message="There is no user with that sub"
    ).json(),
    headers={
        "Content-Type": "application/json; charset=utf-8",
    },
    status_code=404,
)


@router.get(
    "/{sub}/attribution",
    response_model=ReadUserAttributionResponse,
    responses={
        "404": {
            "description": "The user was not found",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def read_user_attribution_info(
    sub: str, authorization: Optional[str] = Header(None)
):
    """Fetches the attribution information about the user with the given sub, i.e.,
    everything that lead up to them creating an account.

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        utms, journey_public_links, first_seen_at = await asyncio.gather(
            get_utms(itgs, sub),
            get_journey_public_links(itgs, sub),
            get_first_seen_at(itgs, sub),
        )

        if first_seen_at is None:
            return USER_NOT_FOUND_RESPONSE

        return Response(
            content=ReadUserAttributionResponse(
                utms=utms,
                journey_public_links=journey_public_links,
                first_seen_at=first_seen_at,
            ).json(),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "private, max-age=86400, stale-while-revalidate=86400, stale-if-error=86400",
            },
        )


async def get_utms(itgs: Itgs, sub: str) -> List[UTMClick]:
    conn = await itgs.conn()
    cursor = conn.cursor("none")

    response = await cursor.execute(
        """
        SELECT
            utms.utm_source,
            utms.utm_medium,
            utms.utm_campaign,
            utms.utm_term,
            utms.utm_content,
            visitor_utms.clicked_at
        FROM visitor_utms, utms
        WHERE
            visitor_utms.utm_id = utms.id
            AND EXISTS (
                SELECT 1 FROM visitor_users, users
                WHERE
                    visitor_users.visitor_id = visitor_utms.visitor_id
                    AND visitor_users.user_id = users.id
                    AND users.sub = ?
                    AND users.created_at >= visitor_utms.clicked_at
            )
        ORDER BY visitor_utms.clicked_at DESC
        LIMIT 4
        """,
        (sub,),
    )

    return [
        UTMClick(
            utm_source=utm_source,
            utm_medium=utm_medium,
            utm_campaign=utm_campaign,
            utm_term=utm_term,
            utm_content=utm_content,
            clicked_at=clicked_at,
        )
        for (
            utm_source,
            utm_medium,
            utm_campaign,
            utm_term,
            utm_content,
            clicked_at,
        ) in (response.results or [])
    ]


async def get_journey_public_links(itgs: Itgs, sub: str) -> List[JourneyPublicLinkView]:
    conn = await itgs.conn()
    cursor = conn.cursor("none")

    response = await cursor.execute(
        """
        SELECT
            journeys.uid,
            journey_public_links.code,
            journey_public_link_views.created_at
        FROM journey_public_link_views, journey_public_links, journeys, users AS target_users
        WHERE
            journey_public_link_views.journey_public_link_id = journey_public_links.id
            AND journey_public_links.journey_id = journeys.id
            AND target_users.sub = ?
            AND target_users.created_at >= journey_public_link_views.created_at
            AND (
                journey_public_link_views.user_id = target_users.id
                OR EXISTS (
                    SELECT 1 FROM visitor_users
                    WHERE
                        visitor_users.visitor_id = journey_public_link_views.visitor_id
                        AND visitor_users.user_id = target_users.id
                )
            )
        ORDER BY journey_public_link_views.created_at DESC
        LIMIT 4
        """,
        (sub,),
    )

    incomplete_by_uid: Dict[str, Tuple[str, float]] = dict(
        (uid, (code, created_at))
        for (uid, code, created_at) in (response.results or [])
    )
    if len(incomplete_by_uid) == 0:
        return []

    fetched_journeys = await raw_read_journeys(
        itgs,
        [("uid", FilterInItem(list(incomplete_by_uid.keys())))],
        [],
        len(incomplete_by_uid),
    )

    if len(incomplete_by_uid) != len(fetched_journeys):
        raise Exception("journeys_by_uid is missing some journeys")

    return sorted(
        [
            JourneyPublicLinkView(
                journey=journey,
                code=incomplete_by_uid[journey.uid][0],
                clicked_at=incomplete_by_uid[journey.uid][1],
            )
            for journey in fetched_journeys
        ],
        key=lambda jplv: jplv.clicked_at,
        reverse=True,
    )


async def get_first_seen_at(itgs: Itgs, sub: str) -> Optional[float]:
    conn = await itgs.conn()
    cursor = conn.cursor("none")

    response = await cursor.execute(
        """
        WITH earliest_visitors AS (
            SELECT 
                MIN(visitors.created_at) AS created_at
            FROM visitors, visitor_users, users
            WHERE
                visitors.id = visitor_users.visitor_id
                AND visitor_users.user_id = users.id
                AND users.sub = ?
        )
        SELECT
            (CASE
                WHEN earliest_visitors.created_at IS NOT NULL THEN MIN(earliest_visitors.created_at, users.created_at)
                ELSE users.created_at
            END) AS first_seen_at
        FROM users
        LEFT OUTER JOIN earliest_visitors ON 1
        WHERE
            users.sub = ?
        """,
        (sub, sub),
    )

    if not response.results:
        return None

    return response.results[0][0]
