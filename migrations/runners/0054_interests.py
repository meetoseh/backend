import secrets
from typing import Dict, List, Optional
from itgs import Itgs
from utms.lib.parse import UTM, get_canonical_utm_representation_from_wrapped
import time
import json


async def up(itgs: Itgs):
    """Creates tables related to interests, so that users can have a tailored
    experience based on where they came from. AFter creating the schemas, it
    populates the tables based on the known utm associations.
    """
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.execute(
        """
        CREATE TABLE interests (
            id INTEGER PRIMARY KEY,
            slug TEXT UNIQUE NOT NULL
        )
        """
    )

    await cursor.executemany2(
        (
            """
            CREATE TABLE visitor_interests (
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                visitor_id INTEGER NOT NULL REFERENCES visitors(id) ON DELETE CASCADE,
                interest_id INTEGER NOT NULL REFERENCES interests(id) ON DELETE CASCADE,
                is_primary BOOLEAN NOT NULL,
                add_reason TEXT NOT NULL,
                created_at REAL NOT NULL,
                deleted_reason TEXT NULL,
                deleted_at REAL NULL
            )
            """,
            "CREATE INDEX visitor_interests_visitor_id_idx ON visitor_interests(visitor_id)",
            "CREATE INDEX visitor_interests_interest_id_idx ON visitor_interests(interest_id)",
            "CREATE UNIQUE INDEX visitor_interests_primary_idx ON visitor_interests(visitor_id) WHERE is_primary=1 AND deleted_at IS NULL",
            "CREATE UNIQUE INDEX visitor_interests_active_rels_idx ON visitor_interests(visitor_id, interest_id) WHERE deleted_at IS NULL",
        ),
        transaction=False,
    )

    await cursor.executemany2(
        (
            """
            CREATE TABLE user_interests (
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                interest_id INTEGER NOT NULL REFERENCES interests(id) ON DELETE CASCADE,
                is_primary BOOLEAN NOT NULL,
                add_reason TEXT NOT NULL,
                created_at REAL NOT NULL,
                deleted_reason TEXT NULL,
                deleted_at REAL NULL
            )
            """,
            "CREATE INDEX user_interests_user_id_idx ON user_interests(user_id)",
            "CREATE INDEX user_interests_interest_id_idx ON user_interests(interest_id)",
            "CREATE UNIQUE INDEX user_interests_primary_idx ON user_interests(user_id) WHERE is_primary=1 AND deleted_at IS NULL",
            "CREATE UNIQUE INDEX user_interests_active_rels_idx ON user_interests(user_id, interest_id) WHERE deleted_at IS NULL",
        ),
        transaction=False,
    )

    await cursor.execute(
        """
        INSERT INTO interests (slug)
        VALUES (?), (?), (?)
        """,
        ("sleep", "anxiety", "mindful"),
    )

    await fill_visitor_interests(
        itgs,
        utms_by_interest={
            "sleep": [
                UTM(
                    source="oseh.com",
                    medium="referral",
                    campaign="headline",
                    content="sleep",
                ),
            ],
            "anxiety": [
                # https://oseh-dev.com:3000/?utm_source=oseh.com&utm_medium=referral&utm_campaign=headline&utm_content=anxiety
                UTM(
                    source="oseh.com",
                    medium="referral",
                    campaign="headline",
                    content="anxiety",
                ),
                UTM(
                    source="oseh.com",
                    medium="referral",
                    campaign="headline",
                    content="therapist",
                ),
            ],
            "mindful": [
                UTM(
                    source="oseh.com",
                    medium="referral",
                    campaign="headline",
                    content="mindful",
                ),
            ],
        },
    )
    await fill_user_interests(itgs)


async def fill_visitor_interests(
    itgs: Itgs, *, utms_by_interest: Dict[str, List[UTM]]
) -> None:
    """For each visitor, if their last utm matches any of the given utms, they are
    associated with the corresponding interest.
    """
    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    all_canonical_utms = [
        get_canonical_utm_representation_from_wrapped(utm)
        for utms in utms_by_interest.values()
        for utm in utms
    ]

    canonical_utm_to_interest = dict(
        (get_canonical_utm_representation_from_wrapped(utm), interest_slug)
        for interest_slug, utms in utms_by_interest.items()
        for utm in utms
    )

    if len(all_canonical_utms) == 0:
        utms_match_query = "0"
    elif len(all_canonical_utms) == 1:
        utms_match_query = "utms.canonical_query_param = ?"
    else:
        utms_match_query = (
            "utms.canonical_query_param IN ("
            + ",".join("?" * len(all_canonical_utms))
            + ")"
        )

    utms_match_params = all_canonical_utms

    now = time.time()

    last_vis_uid: Optional[str] = None
    batch_size = 50
    while True:
        response = await cursor.execute(
            f"""
            SELECT
                visitors.uid,
                utms.canonical_query_param
            FROM visitors, visitor_utms, utms
            WHERE
                (? IS NULL OR visitors.uid > ?)
                AND NOT EXISTS (
                    SELECT 1 FROM visitor_interests
                    WHERE visitor_interests.visitor_id = visitors.id
                )
                AND visitor_utms.visitor_id = visitors.id
                AND visitor_utms.utm_id = utms.id
                AND ({utms_match_query})
                AND NOT EXISTS (
                    SELECT 1 FROM visitor_utms AS other_visitor_utms
                    WHERE
                        (
                            other_visitor_utms.clicked_at > visitor_utms.clicked_at
                            OR (
                                other_visitor_utms.clicked_at = visitor_utms.clicked_at
                                AND other_visitor_utms.uid > visitor_utms.uid
                            )
                        )
                        AND other_visitor_utms.visitor_id = visitors.id
                )
            ORDER BY visitors.uid ASC
            LIMIT ?
            """,
            (last_vis_uid, last_vis_uid, *utms_match_params, batch_size),
        )
        if not response.results:
            break

        vis_uid = None
        for vis_uid, source_canonical_utm in response.results:
            interest_slug = canonical_utm_to_interest[source_canonical_utm]
            vint_uid = f"oseh_vi_{secrets.token_urlsafe(16)}"
            await cursor.execute(
                """
                INSERT INTO visitor_interests (
                    uid, visitor_id, interest_id, is_primary, add_reason, created_at
                )
                SELECT
                    ?, visitors.id, interests.id, 1, ?, ?
                FROM visitors, interests
                WHERE
                    visitors.uid = ?
                    AND interests.slug = ?
                """,
                (
                    vint_uid,
                    json.dumps({"type": "utm", "utm": source_canonical_utm}),
                    now,
                    vis_uid,
                    interest_slug,
                ),
            )

        last_vis_uid = vis_uid


async def fill_user_interests(itgs: Itgs):
    """For each user, looks at the most recently seen visitor relationship with
    interests and copies those interests over. This relies on there only being
    at most one interest per visitor and it isn't deleted.
    """
    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    now = time.time()

    last_user_sub: Optional[str] = None
    batch_size = 50
    while True:
        response = await cursor.execute(
            """
            SELECT
                users.sub,
                interests.slug,
                visitor_interests.uid
            FROM users, visitor_users, visitor_interests, interests
            WHERE
                (? IS NULL OR users.sub > ?)
                AND visitor_users.user_id = users.id
                AND visitor_interests.visitor_id = visitor_users.visitor_id
                AND interests.id = visitor_interests.interest_id
                AND NOT EXISTS (
                    SELECT 1 FROM user_interests
                    WHERE user_interests.user_id = users.id
                )
                AND NOT EXISTS (
                    SELECT 1 FROM visitor_users AS vu, visitor_interests AS vi
                    WHERE
                        vu.user_id = users.id
                        AND vu.visitor_id = vi.visitor_id
                        AND (
                            vu.last_seen_at > visitor_users.last_seen_at
                            OR (
                                vu.last_seen_at = visitor_users.last_seen_at
                                AND vu.uid > visitor_users.uid
                            )
                        )
                )
            ORDER BY users.sub ASC
            LIMIT ?
            """,
            (last_user_sub, last_user_sub, batch_size),
        )
        if not response.results:
            break

        user_sub = None
        for user_sub, interest_slug, vint_uid in response.results:
            uint_uid = f"oseh_uint_{secrets.token_urlsafe(16)}"
            await cursor.execute(
                """
                INSERT INTO user_interests (
                    uid, user_id, interest_id, is_primary, add_reason, created_at
                )
                SELECT
                    ?, users.id, interests.id, 1, ?, ?
                FROM users, interests
                WHERE
                    users.sub = ?
                    AND interests.slug = ?
                """,
                (
                    uint_uid,
                    json.dumps(
                        {"type": "copy_visitor", "visitor_interest_uid": vint_uid}
                    ),
                    now,
                    user_sub,
                    interest_slug,
                ),
            )

        last_user_sub = user_sub
