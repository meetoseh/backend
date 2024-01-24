import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, StringConstraints
from typing import Annotated, Optional, cast
import pytz
import auth
from error_middleware import handle_warning
from itgs import Itgs
from journeys.lib.link_stats import (
    ViewClientConfirmFailedDatabase,
    ViewClientConfirmFailedRedis,
    ViewClientConfirmedDatabase,
    ViewClientConfirmedRedis,
    journey_share_link_stats,
)
from redis_helpers.run_with_prep import run_with_prep
from redis_helpers.share_links_confirm_view import (
    ShareLinkConfirmViewFailureResult,
    ShareLinkConfirmViewSuccessResult,
    ensure_share_links_confirm_view_script_exists,
    share_links_confirm_view,
)
from visitors.lib.get_or_create_visitor import check_visitor_sanity
import unix_dates

router = APIRouter()


class ConfirmShareLinkViewRequest(BaseModel):
    view_uid: Annotated[str, StringConstraints(min_length=2, max_length=255)] = Field(
        description="The UID of the view to confirm"
    )


tz = pytz.timezone("America/Los_Angeles")


@router.post("/confirm_share_link_view", status_code=202)
async def confirm_share_link_view(
    args: ConfirmShareLinkViewRequest,
    authorization: Annotated[Optional[str], Header()] = None,
    visitor: Annotated[Optional[str], Header()] = None,
):
    """Used by a client which received a hydrated page for a share link
    to confirm that it was able to view the content. This improves our
    ability to detect malicious behavior.

    Clients SHOULD provide standard authorization and visitor headers
    """
    request_at = time.time()
    request_unix_date = unix_dates.unix_timestamp_to_unix_date(request_at, tz=tz)
    async with Itgs() as itgs, journey_share_link_stats(itgs) as stats:
        auth_result = await auth.auth_any(itgs, authorization)
        cleaned_visitor = check_visitor_sanity(visitor)

        stats.incr_view_client_confirmation_requests(
            unix_date=request_unix_date,
            visitor_provided=cleaned_visitor is not None,
            user_provided=auth_result.success,
        )

        redis = await itgs.redis()

        async def prepare(force: bool):
            await ensure_share_links_confirm_view_script_exists(redis, force=force)

        async def execute():
            return await share_links_confirm_view(
                redis,
                args.view_uid,
                user_sub=auth_result.result.sub
                if auth_result.result is not None
                else None,
                visitor=cleaned_visitor,
                confirmed_at=request_at,
            )

        result = await run_with_prep(prepare, execute)
        assert result is not None

        if result.success:
            result = cast(ShareLinkConfirmViewSuccessResult, result)
            stats.incr_view_client_confirmed(
                unix_date=request_unix_date,
                extra=ViewClientConfirmedRedis(
                    details=result.details,
                ),
            )
            if cleaned_visitor is not None and result.link_uid is not None:
                conn = await itgs.conn()
                cursor = conn.cursor("none")
                response = await cursor.execute(
                    """
                    SELECT
                        journey_subcategories.internal_name,
                        users.sub
                    FROM journey_share_links, journeys, journey_subcategories
                    LEFT OUTER JOIN users ON users.id = journey_share_links.user_id
                    WHERE
                        journey_share_links.uid = ?
                        AND journeys.id = journey_share_links.journey_id
                        AND journey_subcategories.id = journeys.journey_subcategory_id
                    """,
                    (result.link_uid,),
                )

                if response.results:
                    journey_subcategory_internal_name = cast(
                        str, response.results[0][0]
                    )
                    sharer_sub = cast(Optional[str], response.results[0][1])
                    await stats.incr_immediately_journey_share_link_unique_views(
                        itgs=itgs,
                        unix_date=request_unix_date,
                        visitor_uid=cleaned_visitor,
                        journey_subcategory_internal_name=journey_subcategory_internal_name,
                        code=result.link_code,
                        sharer_sub=sharer_sub,
                        view_uid=args.view_uid,
                    )
                else:
                    await handle_warning(
                        f"{__name__}:link_missing",
                        f"Not incrementing unique views for link {result.link_uid} because the "
                        "required auxilary information was not available in the database",
                    )
            return Response(status_code=202)

        result = cast(ShareLinkConfirmViewFailureResult, result)
        if result.details != "not_in_pseudoset":
            stats.incr_view_client_confirm_failed(
                unix_date=request_unix_date,
                extra=ViewClientConfirmFailedRedis(
                    details=result.details,
                ),
            )
            return Response(status_code=202)

        conn = await itgs.conn()
        cursor = conn.cursor()

        max_view_age = request_at - 60 * 60
        response = await cursor.executeunified3(
            (
                (
                    """
                    SELECT 
                        journey_share_link_views.created_at,
                        journey_share_links.code,
                        journey_subcategories.internal_name,
                        users.sub
                    FROM journey_share_link_views, journey_share_links, journeys, journey_subcategories
                    LEFT OUTER JOIN users ON users.id = journey_share_links.user_id
                    WHERE 
                        journey_share_link_views.uid = ?
                        AND journey_share_link_views.journey_share_link_id = journey_share_links.id
                        AND journeys.id = journey_share_links.journey_id
                        AND journey_subcategories.id = journeys.journey_subcategory_id
                    """,
                    (args.view_uid,),
                ),
                (
                    """
                    WITH faked(value) AS (VALUES (1)),
                    batch(user_id, visitor_id) AS (
                    SELECT
                        users.id,
                        visitors.id
                    FROM faked
                    LEFT OUTER JOIN users ON users.sub=?
                    LEFT OUTER JOIN visitors ON visitors.uid=?
                    )
                    UPDATE journey_share_link_views
                    SET
                        user_id=batch.user_id,
                        visitor_id=batch.visitor_id,
                        user_set=batch.user_id IS NOT NULL,
                        visitor_set=batch.visitor_id IS NOT NULL,
                        confirmed_at=?
                    FROM batch
                    WHERE
                        journey_share_link_views.uid = ?
                        AND journey_share_link_views.confirmed_at IS NULL
                        AND journey_share_link_views.created_at > ?
                    """,
                    (
                        auth_result.result.sub
                        if auth_result.result is not None
                        else None,
                        cleaned_visitor,
                        request_at,
                        args.view_uid,
                        max_view_age,
                    ),
                ),
            )
        )

        link_view_exists: bool = False
        link_view_too_old: bool = False
        link_code: Optional[str] = None
        journey_subcategory_internal_name: Optional[str] = None
        sharer_sub: Optional[str] = None

        if response[0].results:
            link_view_exists = True
            link_view_too_old = response[0].results[0][0] <= max_view_age
            link_code = cast(str, response[0].results[0][1])
            journey_subcategory_internal_name = cast(str, response[0].results[0][2])
            sharer_sub = cast(Optional[str], response[0].results[0][3])

        confirmed_view = (
            response[1].rows_affected is not None and response[1].rows_affected > 0
        )

        if confirmed_view:
            stats.incr_view_client_confirmed(
                unix_date=request_unix_date, extra=ViewClientConfirmedDatabase()
            )
            if cleaned_visitor is not None:
                if (
                    link_code is not None
                    and journey_subcategory_internal_name is not None
                ):
                    await stats.incr_immediately_journey_share_link_unique_views(
                        itgs=itgs,
                        unix_date=request_unix_date,
                        visitor_uid=cleaned_visitor,
                        journey_subcategory_internal_name=journey_subcategory_internal_name,
                        code=link_code,
                        sharer_sub=sharer_sub,
                        view_uid=args.view_uid,
                    )
                else:
                    await handle_warning(
                        f"{__name__}:integrity_error",
                        f"Not incrementing unique views for link {args.view_uid} because the "
                        "expected auxilary information (link code, subcategory internal name) "
                        "was not available in the database",
                    )

            return Response(status_code=202)

        stats.incr_view_client_confirm_failed(
            unix_date=request_unix_date,
            extra=ViewClientConfirmFailedDatabase(
                details="not_found"
                if not link_view_exists
                else ("too_old" if link_view_too_old else "already_confirmed")
            ),
        )
        return Response(status_code=202)
