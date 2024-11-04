import json
from typing import List, cast
from error_middleware import handle_warning
from itgs import Itgs


async def extract_choices(
    itgs: Itgs, /, *, user_sub: str, given: List[str], default: List[str]
) -> List[str]:
    if len(given) != 1 or given[0] != "[0] __appfix":
        return given

    conn = await itgs.conn()
    cursor = conn.cursor()
    response = await cursor.execute(
        """
SELECT
    json_extract(user_client_screen_actions_log.event, '$.value') AS value
FROM 
    user_client_screen_actions_log,
    user_client_screens_log,
    users
WHERE
    user_client_screen_actions_log.user_client_screen_log_id = user_client_screens_log.id
    AND user_client_screens_log.user_id = users.id
    AND users.sub = ?
    AND json_extract(user_client_screen_actions_log.event, '$.type') = 'checked-changed'
ORDER BY 
    user_client_screens_log.created_at DESC,
    user_client_screen_actions_log.created_at DESC,
    user_client_screen_actions_log.uid ASC
LIMIT 1
        """,
        (user_sub,),
    )
    if not response.results:
        await handle_warning(
            f"{__name__}:no_checked_changed",
            f"Failed to determine what was checked for app hotfix choices for user {user_sub}, using default",
        )
        return default

    value = cast(List[str], json.loads(response.results[0][0]))
    await handle_warning(
        f"{__name__}:fallback_checked",
        f"Used fallback for choices for user {user_sub}: {value}",
    )
    return value
