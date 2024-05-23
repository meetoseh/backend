import json
import secrets
import time
from typing import List, Optional, Set
from itgs import Itgs
from lib.client_flows.executor import ClientScreenQueuePeekInfo
from lib.client_flows.helper import produce_screen_input_parameters
from users.me.screens.lib.standard_parameters import (
    create_standard_parameters,
    get_requested_standard_parameters,
)
from users.me.screens.models.peeked_screen import (
    PeekScreenResponse,
    PeekedScreen,
    PeekedScreenItem,
)
from users.me.screens.auth import create_jwt as create_screen_jwt
from visitors.lib.get_or_create_visitor import VisitorSource, check_visitor_sanity
from visitors.routes.associate_visitor_with_user import push_visitor_user_association


async def realize_screens(
    itgs: Itgs,
    /,
    *,
    user_sub: str,
    platform: VisitorSource,
    visitor: Optional[str],
    result: ClientScreenQueuePeekInfo,
) -> PeekScreenResponse:
    now = time.time()
    visitor = check_visitor_sanity(visitor)
    requested_standard_parameters: Set[tuple] = set()
    for path in get_requested_standard_parameters(result.front.flow_screen.screen):
        requested_standard_parameters.add(tuple(path))
    for itm in result.prefetch:
        for path in get_requested_standard_parameters(itm.flow_screen.screen):
            requested_standard_parameters.add(tuple(path))

    standard_parameters = await create_standard_parameters(
        itgs, user_sub=user_sub, requested=requested_standard_parameters, now=now
    )

    active = PeekedScreenItem(
        slug=result.front.screen.slug,
        parameters=await result.front.screen.realizer.convert_validated_to_realized(
            itgs,
            for_user_sub=user_sub,
            input=produce_screen_input_parameters(
                flow_screen=result.front.flow_screen,
                flow_client_parameters=result.front.flow_client_parameters,
                transformed_flow_server_parameters=result.front.flow_server_parameters,
                standard_parameters=standard_parameters,
            ),
        ),
    )

    prefetch: List[PeekedScreenItem] = []
    for itm in result.prefetch:
        prefetch.append(
            PeekedScreenItem(
                slug=itm.screen.slug,
                parameters=await itm.screen.realizer.convert_validated_to_realized(
                    itgs,
                    for_user_sub=user_sub,
                    input=produce_screen_input_parameters(
                        flow_screen=itm.flow_screen,
                        flow_client_parameters=itm.flow_client_parameters,
                        transformed_flow_server_parameters=itm.flow_server_parameters,
                        standard_parameters=standard_parameters,
                    ),
                ),
            )
        )

    log_uid = f"oseh_ucsl_{secrets.token_urlsafe(16)}"
    new_visitor = f"oseh_v_{secrets.token_urlsafe(16)}"
    conn = await itgs.conn()
    cursor = conn.cursor()

    response = await cursor.executeunified3(
        (
            (
                """
INSERT INTO visitors(uid, version, source, created_at)
SELECT ?, 1, ?, ?
WHERE ? IS NULL OR NOT EXISTS (
    SELECT 1 FROM visitors AS v
    WHERE v.uid = ?
)
                """,
                (new_visitor, platform, now, visitor, visitor),
            ),
            (
                """
INSERT INTO user_client_screens_log (
    uid, user_id, platform, visitor_id, screen, created_at
)
SELECT
    ?, users.id, ?, visitors.id, ?, ?
FROM users, visitors
WHERE
    users.sub = ? AND visitors.uid IN (?, ?)
                """,
                (
                    log_uid,
                    platform,
                    json.dumps(
                        {
                            "slug": result.front.screen.slug,
                            "parameters": active.parameters,
                        }
                    ),
                    now,
                    user_sub,
                    visitor,
                    new_visitor,
                ),
            ),
        )
    )

    replaced_visitor = (
        response[0].rows_affected is not None and response[0].rows_affected > 0
    )
    if replaced_visitor:
        result_visitor = new_visitor
    else:
        assert visitor is not None
        result_visitor = visitor

    await push_visitor_user_association(itgs, result_visitor, user_sub, now)

    return PeekScreenResponse(
        visitor=result_visitor,
        screen=PeekedScreen(
            active=active,
            active_jwt=await create_screen_jwt(
                itgs,
                user_client_screen_uid=result.front.user_client_screen_uid,
                user_client_screen_log_uid=log_uid,
                screen_slug=result.front.screen.slug,
                duration=60 * 60 * 24 * 7,
            ),
            prefetch=prefetch,
        ),
    )
