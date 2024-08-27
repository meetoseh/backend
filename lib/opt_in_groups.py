import secrets
import socket
import time
from typing import Literal, Optional, overload
from itgs import Itgs


@overload
async def check_if_user_in_opt_in_group(
    itgs: Itgs,
    /,
    *,
    user_sub: str,
    group_name: str,
    create_if_not_exists: Literal[False],
    optimize_for_exists: bool = True,
) -> Optional[bool]: ...


@overload
async def check_if_user_in_opt_in_group(
    itgs: Itgs,
    /,
    *,
    user_sub: str,
    group_name: str,
    create_if_not_exists: Literal[True],
    optimize_for_exists: bool = True,
) -> bool: ...


async def check_if_user_in_opt_in_group(
    itgs: Itgs,
    /,
    *,
    user_sub: str,
    group_name: str,
    create_if_not_exists: bool,
    optimize_for_exists: bool = True,
) -> Optional[bool]:
    """
    Determines if the user with the given sub is in the opt in group with
    the given name. If the group does not exist, the behavior depends on
    `create_if_not_exists`. If the group exists, this will return whether
    the user is in the group.

    Since it's not expected that caching will be helpful for most of the use-cases
    of opt-in-groups (one-time popups, etc), this does not cache and always uses
    weak consistency.

    Args:
        itgs (Itgs): the integrations to (re)use
        user_sub (str): the user's sub to check for
        group_name (str): the group to check in
        create_if_not_exists (bool): if the group should be created if it
            doesn't exist (usually, True). We will send a message to slack
            if we create a new group. If false, if the group does not exist
            this returns None
        optimize_for_exists (bool): A hint for if we should assume the group
            exists for the purposes of optimization. Generally, True. Does not
            effect correctness.

    Returns:
        (bool, None): whether the user is in the group, if the group exists,
            otherwise None
    """
    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    if not create_if_not_exists or optimize_for_exists:
        result = await cursor.execute(
            """
SELECT
    EXISTS (
        SELECT 1 FROM users, opt_in_group_users 
        WHERE
            users.sub = ?
            AND opt_in_group_users.user_id = users.id
            AND opt_in_group_users.opt_in_group_id = opt_in_groups.id
    ) AS in_group
FROM opt_in_groups
WHERE opt_in_groups.name = ? COLLATE NOCASE
            """,
            (user_sub, group_name),
        )
        if not result.results:
            if create_if_not_exists:
                return await check_if_user_in_opt_in_group(
                    itgs,
                    user_sub=user_sub,
                    group_name=group_name,
                    create_if_not_exists=True,
                    optimize_for_exists=False,
                )
            return None

        return bool(result.results[0][0])

    new_group_uid = f"oseh_oig_{secrets.token_urlsafe(16)}"
    new_group_created_at = time.time()
    result = await cursor.executeunified3(
        (
            (
                """
INSERT INTO opt_in_groups (
    uid, name, created_at
)
SELECT
    ?, ?, ?
WHERE
    NOT EXISTS (
        SELECT 1 FROM opt_in_groups AS oig
        WHERE oig.name = ? COLLATE NOCASE
    )
                """,
                [new_group_uid, group_name, new_group_created_at, group_name],
            ),
            (
                """
SELECT 1 FROM users, opt_in_group_users, opt_in_groups
WHERE
    users.sub = ?
    AND opt_in_group_users.user_id = users.id
    AND opt_in_group_users.opt_in_group_id = opt_in_groups.id
    AND opt_in_groups.name = ? COLLATE NOCASE
                """,
                [user_sub, group_name],
            ),
        )
    )

    if result[0].rows_affected:
        slack = await itgs.slack()
        await slack.send_ops_message(
            f"{socket.gethostname()} created opt in group `{group_name}`"
        )

    return not not result[1].results
