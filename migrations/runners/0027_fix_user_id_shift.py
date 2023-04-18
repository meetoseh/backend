from typing import Dict, List, Optional, Tuple
from itgs import Itgs
from loguru import logger
import json
from dataclasses import dataclass
import os


@dataclass
class UserIdentityRow:
    id: int
    uid: str
    user_id: int
    provider: str
    sub: str
    example_claims: dict
    created_at: int
    last_seen_at: int


def parse_row(row: list) -> UserIdentityRow:
    return UserIdentityRow(
        id=row[0],
        uid=row[1],
        user_id=row[2],
        provider=row[3],
        sub=row[4],
        example_claims=json.loads(row[5]),
        created_at=row[6],
        last_seen_at=row[7],
    )


async def up(itgs: Itgs):
    """Fixes an egregious error in the previous migration which caused ids to shift;
    I sort of spotted it when copilot filled it but it didn't connect just how bad
    it would be

    Because row ids shifted, everything relating to users is now referencing the wrong
    row... the worst is people login to the wrong account
    """
    conn = await itgs.conn()
    cursor = conn.cursor()

    slack = await itgs.slack()
    uncorrupted_to_corrupted_id_map: Dict[int, int] = dict()
    uncorrupted_with_no_corrupted_id: List[int] = []

    last_user_identity_user_id: Optional[int] = None
    while True:
        response = await cursor.execute(
            """
            SELECT
                id, uid, user_id, provider, sub, example_claims, created_at, last_seen_at
            FROM user_identities
            WHERE
                (? IS NULL OR user_identities.user_id > ?)
            ORDER BY user_identities.user_id ASC
            LIMIT 1
            """,
            (last_user_identity_user_id, last_user_identity_user_id),
        )
        if not response.results:
            break

        base_identity = parse_row(response.results[0])
        last_user_identity_user_id = base_identity.user_id
        logger.debug(f"Reconciling user identity: {base_identity}...")
        logger.debug(
            "Fetching all other matching identities pointing at the same user id..."
        )

        response = await cursor.execute(
            """
            SELECT
                id, uid, user_id, provider, sub, example_claims, created_at, last_seen_at
            FROM user_identities
            WHERE
                user_identities.user_id = ?
                AND user_identities.id != ?
            """,
            (
                base_identity.user_id,
                base_identity.id,
            ),
        )

        other_identities = [parse_row(row) for row in (response.results or [])]

        logger.debug(f"Other identities: {other_identities}")

        identity_emails: List[str] = []
        identity_emails.append(base_identity.example_claims["email"])
        for identity in other_identities:
            identity_emails.append(identity.example_claims["email"])
        identity_emails.sort()
        logger.debug(f"Identity emails: {identity_emails}")

        not_private_emails = [
            email for email in identity_emails if "privaterelay" not in email
        ]
        private_emails = [email for email in identity_emails if "privaterelay" in email]

        matched_user_id: Optional[int] = None
        for email in not_private_emails + private_emails:
            response = await cursor.execute(
                "SELECT id FROM users WHERE email = ?", (email,)
            )
            if response.results:
                matched_user_id = response.results[0][0]
                break

        if matched_user_id is None:
            logger.debug(f"Failed to find the new user id for {base_identity}")
            uncorrupted_with_no_corrupted_id.append(base_identity.user_id)
        else:
            uncorrupted_to_corrupted_id_map[base_identity.user_id] = matched_user_id
            logger.debug(
                f"User with id {matched_user_id} used to have the id {base_identity.id} but now has id {matched_user_id}"
            )

    logger.info(f"Uncorrupted to corrupted map: {uncorrupted_to_corrupted_id_map}")
    logger.info(f"Users with no post shift id: {uncorrupted_with_no_corrupted_id}")

    env = os.environ["ENVIRONMENT"]
    await slack.send_ops_message(
        f"{env=} Uncorrupted to corrupted id map:\n\n```{json.dumps(uncorrupted_to_corrupted_id_map)}\n```"
    )
    await slack.send_ops_message(
        f"{env=} Uncorrupted user ids with no corrupted counterpart:\n\n```{json.dumps(uncorrupted_with_no_corrupted_id)}\n```"
    )

    if uncorrupted_with_no_corrupted_id:
        raise Exception(
            "There are users with a corrupted id that we can't fix, aborting"
        )

    queries_to_execute: List[Tuple[str, list]] = []
    queries_to_execute.append(("PRAGMA foreign_keys = OFF", []))
    queries_to_execute.append(("UPDATE users SET id=id+1000", []))
    for uncorrupted_id, corrupted_id in uncorrupted_to_corrupted_id_map.items():
        queries_to_execute.append(
            ("UPDATE users SET id=? WHERE id=?", [uncorrupted_id, corrupted_id + 1000])
        )
    queries_to_execute.append(("PRAGMA foreign_keys = ON", []))

    await cursor.executemany3(queries_to_execute, transaction=False)
