"""Fleshes out contact methods so that we can support an arbitrary
number of email addresses/phone numbers/push tokens for a user, plus those
email addresses/phone numbers/push tokens can each be individually suppressed or
disabled in a consistent way
"""
import io
import json
import secrets
from typing import List, Optional, Tuple
from error_middleware import handle_warning
from itgs import Itgs
from temp_files import temp_file
import time
from dataclasses import dataclass
from loguru import logger
import unix_dates
import pytz
from lib.contact_methods.contact_method_stats import contact_method_stats


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    files = await itgs.files()
    with temp_file(".bak") as backup_file:
        with open(backup_file, "wb") as f:
            await conn.backup(f)

        with open(backup_file, "rb") as f:
            await files.upload(
                f,
                bucket=files.default_bucket,
                key=f"s3_files/backup/database/timely/0095_contact_methods-{int(time.time())}.bak",
                sync=True,
            )

    await cursor.executemany2(
        (
            """
            CREATE TABLE user_email_addresses(
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                email TEXT NOT NULL,
                verified BOOLEAN NOT NULL,
                receives_notifications BOOLEAN NOT NULL,
                created_at REAL NOT NULL
            )
            """,
            "CREATE INDEX user_email_addresses_user_idx ON user_email_addresses(user_id)",
            "CREATE INDEX user_email_addresses_email_idx ON user_email_addresses(email)",
            """
            CREATE TABLE user_phone_numbers (
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                phone_number TEXT NOT NULL,
                verified BOOLEAN NOT NULL,
                receives_notifications BOOLEAN NOT NULL,
                created_at REAL NOT NULL
            )
            """,
            "CREATE INDEX user_phone_numbers_user_idx ON user_phone_numbers(user_id)",
            "CREATE INDEX user_phone_numbers_phone_number_idx ON user_phone_numbers(phone_number)",
            """
            CREATE TABLE contact_method_log (
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                channel TEXT NOT NULL,
                identifier TEXT NOT NULL,
                action TEXT NOT NULL,
                reason TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """,
            "CREATE INDEX contact_method_log_user_id_idx ON contact_method_log(user_id)",
            """
            CREATE TABLE contact_method_stats (
                id INTEGER PRIMARY KEY,
                retrieved_for TEXT UNIQUE NOT NULL,
                retrieved_at REAL NOT NULL,
                created INTEGER NOT NULL,
                created_breakdown TEXT NOT NULL,
                deleted INTEGER NOT NULL,
                deleted_breakdown TEXT NOT NULL,
                verified INTEGER NOT NULL,
                verified_breakdown TEXT NOT NULL,
                enabled_notifications INTEGER NOT NULL,
                enabled_notifications_breakdown TEXT NOT NULL,
                disabled_notifications INTEGER NOT NULL,
                disabled_notifications_breakdown TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE user_timezone_log (
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                timezone TEXT NOT NULL,
                source TEXT NOT NULL,
                style TEXT NOT NULL,
                guessed BOOLEAN NOT NULL,
                created_at REAL NOT NULL
            )
            """,
            "CREATE INDEX user_timezone_log_user_created_at_idx ON user_timezone_log(user_id, created_at)",
        ),
        transaction=False,
    )

    batch_size = 100
    last_user_sub: Optional[str] = None

    email_batch: List[_Email] = []
    phone_batch: List[_Phone] = []
    timezone_batch: List[_Timezone] = []

    while True:
        response = await cursor.execute(
            """
            SELECT
                sub,
                email,
                email_verified,
                phone_number,
                phone_number_verified,
                timezone,
                timezone_technique
            FROM users
            WHERE
                ? IS NULL OR sub > ?
            ORDER BY sub ASC
            LIMIT ?
            """,
            (last_user_sub, last_user_sub, batch_size),
        )

        if not response.results:
            break

        for (
            row_sub,
            row_email,
            row_email_verified,
            row_phone_number,
            row_phone_number_verified,
            row_timezone,
            row_timezone_technique,
        ) in response.results:
            if row_email is not None:
                email_batch.append(
                    _Email(
                        user_sub=row_sub,
                        email=row_email,
                        verified=bool(row_email_verified),
                        uea_uid=f"oseh_uea_{secrets.token_urlsafe(16)}",
                        cml_uid=f"oseh_cml_{secrets.token_urlsafe(16)}",
                    )
                )
                if len(email_batch) >= batch_size:
                    await write_email_batch(itgs, email_batch)
                    email_batch = []

            if row_phone_number is not None:
                phone_batch.append(
                    _Phone(
                        user_sub=row_sub,
                        number=row_phone_number,
                        verified=bool(row_phone_number_verified),
                        upn_uid=f"oseh_upn_{secrets.token_urlsafe(16)}",
                        cml_uid=f"oseh_cml_{secrets.token_urlsafe(16)}",
                    )
                )
                if len(phone_batch) >= batch_size:
                    await write_phone_batch(itgs, phone_batch)
                    phone_batch = []

            if row_timezone is not None:
                timezone_batch.append(
                    parse_timezone(row_sub, row_timezone, row_timezone_technique)
                )
                if len(timezone_batch) >= batch_size:
                    await write_timezone_batch(itgs, timezone_batch)
                    timezone_batch = []

            last_user_sub = row_sub

    if email_batch:
        await write_email_batch(itgs, email_batch)

    if phone_batch:
        await write_phone_batch(itgs, phone_batch)

    if timezone_batch:
        await write_timezone_batch(itgs, timezone_batch)

    await cursor.executemany2(
        (
            "PRAGMA foreign_keys = OFF",
            "DROP INDEX users_email_idx",
            """
            CREATE TABLE users_new (
                id INTEGER PRIMARY KEY,
                sub TEXT UNIQUE NOT NULL,
                given_name TEXT,
                family_name TEXT,
                admin BOOLEAN NOT NULL,
                revenue_cat_id TEXT UNIQUE NOT NULL,
                timezone TEXT NULL,
                created_at REAL NOT NULL
            )
            """,
            """
            INSERT INTO users_new (
                id, sub, given_name, family_name, admin, revenue_cat_id, timezone, created_at
            )
            SELECT
                id, sub, given_name, family_name, admin, revenue_cat_id, timezone, created_at
            FROM users
            """,
            "DROP TABLE users",
            "ALTER TABLE users_new RENAME TO users",
            "PRAGMA foreign_keys = ON",
        ),
        transaction=False,
    )

    await cursor.execute(
        """
        CREATE TABLE suppressed_phone_numbers (
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            phone_number TEXT UNIQUE NOT NULL,
            reason TEXT NOT NULL,
            reason_details TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )

    await cursor.executemany2(
        (
            "PRAGMA foreign_keys = OFF",
            "DROP INDEX user_push_tokens_user_id_idx",
            """
            CREATE TABLE user_push_tokens_new (
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                platform TEXT NOT NULL,
                token TEXT UNIQUE NOT NULL,
                receives_notifications BOOLEAN NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                last_seen_at REAL NOT NULL,
                last_confirmed_at REAL NULL
            )
            """,
            """
            INSERT INTO user_push_tokens_new (
                id, uid, user_id, platform, token, receives_notifications, created_at, updated_at, last_seen_at, last_confirmed_at
            )
            SELECT
                id, uid, user_id, platform, token, 1, created_at, updated_at, last_seen_at, last_confirmed_at
            FROM user_push_tokens
            """,
            "DROP TABLE user_push_tokens",
            "ALTER TABLE user_push_tokens_new RENAME TO user_push_tokens",
            "CREATE INDEX user_push_tokens_user_id_idx ON user_push_tokens(user_id)",
            "PRAGMA foreign_keys = ON",
        ),
        transaction=False,
    )

    await cursor.executemany2(
        (
            "PRAGMA foreign_keys = OFF",
            "DROP INDEX phone_verifications_user_id_verified_at_idx",
            "DROP INDEX phone_verifications_verified_at_idx",
            """
            CREATE TABLE phone_verifications_new (
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                sid TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                phone_number TEXT NOT NULL,
                enabled BOOLEAN NOT NULL,
                status TEXT NOT NULL,
                started_at REAL NOT NULL,
                verification_attempts INTEGER NOT NULL,
                verified_at REAL NULL
            )
            """,
            """
            INSERT INTO phone_verifications_new (
                id, uid, sid, user_id, phone_number, enabled, status, started_at, verification_attempts, verified_at
            )
            SELECT
                id, uid, sid, user_id, phone_number, 1, status, started_at, verification_attempts, verified_at
            FROM phone_verifications
            """,
            "DROP TABLE phone_verifications",
            "ALTER TABLE phone_verifications_new RENAME TO phone_verifications",
            "CREATE INDEX phone_verifications_user_id_verified_at_idx ON phone_verifications(user_id, verified_at)",
            "CREATE INDEX phone_verifications_verified_at_idx ON phone_verifications(verified_at) WHERE verified_at IS NOT NULL",
            "PRAGMA foreign_keys = ON",
        ),
        transaction=False,
    )

    with temp_file(".bak") as backup_file:
        with open(backup_file, "wb") as f:
            await conn.backup(f)

        with open(backup_file, "rb") as f:
            await files.upload(
                f,
                bucket=files.default_bucket,
                key=f"s3_files/backup/database/timely/0095_contact_methods-post-{int(time.time())}.bak",
                sync=True,
            )


@dataclass
class _Email:
    user_sub: str
    email: str
    verified: bool
    uea_uid: str
    cml_uid: str


async def write_email_batch(itgs: Itgs, batch: List[_Email]) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()
    now = time.time()
    unix_date = unix_dates.unix_timestamp_to_unix_date(
        now, tz=pytz.timezone("America/Los_Angeles")
    )
    response = await cursor.executemany3(
        (
            make_user_email_addresses_query(batch, now),
            make_email_contact_method_log_query(batch, now),
        )
    )

    if response[0].rows_affected != len(batch) or response[1].rows_affected != len(
        batch
    ):
        logger.warning(f"Bad email {batch=}")
        await handle_warning(
            f"{__name__}:bad_email_batch",
            f"Failed to write email batch: {len(batch)=}, {response=}",
        )

    async with contact_method_stats(itgs) as stats:
        stats.incr_created(
            unix_date,
            channel="email",
            verified=True,
            enabled=True,
            reason="migration",
            amt=sum(email.verified for email in batch),
        )
        stats.incr_created(
            unix_date,
            channel="email",
            verified=False,
            enabled=True,
            reason="migration",
            amt=sum(not email.verified for email in batch),
        )


def make_user_email_addresses_query(
    batch: List[_Email], now: float
) -> Tuple[str, list]:
    query = io.StringIO()
    query.write("WITH batch(sub, uea_uid, email, verified) AS (VALUES (?, ?, ?, ?)")
    for _ in range(len(batch) - 1):
        query.write(", (?, ?, ?, ?)")

    query.write(
        ") INSERT INTO user_email_addresses ("
        " uid, user_id, email, verified, receives_notifications, created_at"
        ") "
        "SELECT"
        " batch.uea_uid,"
        " users.id,"
        " batch.email,"
        " batch.verified,"
        " 1,"
        " ? "
        "FROM batch "
        "JOIN users ON users.sub = batch.sub"
    )

    return (
        query.getvalue(),
        [
            *(
                v
                for email in batch
                for v in (
                    email.user_sub,
                    email.uea_uid,
                    email.email,
                    int(email.verified),
                )
            ),
            now,
        ],
    )


def make_email_contact_method_log_query(
    batch: List[_Email], now: float
) -> Tuple[str, list]:
    query = io.StringIO()
    query.write("WITH batch(sub, cml_uid, email, verified) AS (VALUES (?, ?, ?, ?)")
    for _ in range(len(batch) - 1):
        query.write(", (?, ?, ?, ?)")

    query.write(
        ") INSERT INTO contact_method_log ("
        " uid, user_id, channel, identifier, action, reason, created_at"
        ") "
        "SELECT"
        " batch.cml_uid,"
        " users.id,"
        " 'email',"
        " batch.email,"
        " CASE WHEN batch.verified THEN 'create_verified' ELSE 'create_unverified' END,"
        " ?,"
        " ? "
        "FROM batch "
        "JOIN users ON users.sub = batch.sub"
    )
    return (
        query.getvalue(),
        [
            *(
                v
                for email in batch
                for v in (
                    email.user_sub,
                    email.cml_uid,
                    email.email,
                    int(email.verified),
                )
            ),
            json.dumps({"repo": "backend", "file": __name__}),
            now,
        ],
    )


@dataclass
class _Phone:
    user_sub: str
    number: str
    verified: bool
    upn_uid: str
    cml_uid: str


async def write_phone_batch(itgs: Itgs, batch: List[_Phone]) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()
    now = time.time()
    unix_date = unix_dates.unix_timestamp_to_unix_date(
        now, tz=pytz.timezone("America/Los_Angeles")
    )
    response = await cursor.executemany3(
        (
            make_user_phone_numbers_query(batch, now),
            make_phone_contact_method_log_query(batch, now),
        )
    )

    if response[0].rows_affected != len(batch) or response[1].rows_affected != len(
        batch
    ):
        logger.warning(f"Bad phone {batch=}")
        await handle_warning(
            f"{__name__}:bad_phone_batch",
            f"Failed to write phone batch: {len(batch)=}, {response=}",
        )

    async with contact_method_stats(itgs) as stats:
        stats.incr_created(
            unix_date,
            channel="phone",
            verified=True,
            enabled=True,
            reason="migration",
            amt=sum(phone.verified for phone in batch),
        )
        stats.incr_created(
            unix_date,
            channel="phone",
            verified=False,
            enabled=True,
            reason="migration",
            amt=sum(not phone.verified for phone in batch),
        )


def make_user_phone_numbers_query(batch: List[_Phone], now: float) -> Tuple[str, list]:
    query = io.StringIO()
    query.write(
        "WITH batch(sub, upn_uid, phone_number, verified) AS (VALUES (?, ?, ?, ?)"
    )
    for _ in range(len(batch) - 1):
        query.write(", (?, ?, ?, ?)")

    query.write(
        ") INSERT INTO user_phone_numbers ("
        " uid, user_id, phone_number, verified, receives_notifications, created_at"
        ") "
        "SELECT"
        " batch.upn_uid,"
        " users.id,"
        " batch.phone_number,"
        " batch.verified,"
        " 1,"
        " ? "
        "FROM batch "
        "JOIN users ON users.sub = batch.sub"
    )

    return (
        query.getvalue(),
        [
            *(
                v
                for phone in batch
                for v in (
                    phone.user_sub,
                    phone.upn_uid,
                    phone.number,
                    int(phone.verified),
                )
            ),
            now,
        ],
    )


def make_phone_contact_method_log_query(
    batch: List[_Phone], now: float
) -> Tuple[str, list]:
    query = io.StringIO()
    query.write(
        "WITH batch(sub, cml_uid, phone_number, verified) AS (VALUES (?, ?, ?, ?)"
    )
    for _ in range(len(batch) - 1):
        query.write(", (?, ?, ?, ?)")

    query.write(
        ") INSERT INTO contact_method_log ("
        " uid, user_id, channel, identifier, action, reason, created_at"
        ") "
        "SELECT"
        " batch.cml_uid,"
        " users.id,"
        " 'phone',"
        " batch.phone_number,"
        " CASE WHEN batch.verified THEN 'create_verified' ELSE 'create_unverified' END,"
        " ?,"
        " ? "
        "FROM batch "
        "JOIN users ON users.sub = batch.sub"
    )
    return (
        query.getvalue(),
        [
            *(
                v
                for phone in batch
                for v in (
                    phone.user_sub,
                    phone.cml_uid,
                    phone.number,
                    int(phone.verified),
                )
            ),
            json.dumps({"repo": "backend", "file": __name__}),
            now,
        ],
    )


@dataclass
class _Timezone:
    user_sub: str
    timezone: str
    style: str
    guessed: bool
    utzl_uid: str


def parse_timezone(
    row_user_sub: str, row_timezone: str, row_timezone_technique: str
) -> _Timezone:
    try:
        technique = json.loads(row_timezone_technique)
        assert isinstance(technique, dict)
    except:
        logger.warning(
            f"Failed to parse timezone technique for {row_user_sub=}: {row_timezone_technique=}"
        )
        technique = {"style": "migration", "guessed": True}

    return _Timezone(
        user_sub=row_user_sub,
        timezone=row_timezone,
        style=str(technique.get("style", "migration")),
        guessed=bool(technique.get("guessed", False)),
        utzl_uid=f"oseh_utzl_{secrets.token_urlsafe(16)}",
    )


async def write_timezone_batch(itgs: Itgs, batch: List[_Timezone]) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()
    now = time.time()
    response = await cursor.execute(
        *make_user_timezone_log_query(batch, now),
    )

    if response.rows_affected != len(batch):
        logger.warning(f"Bad timezone {batch=}")
        await handle_warning(
            f"{__name__}:bad_timezone_batch",
            f"Failed to write timezone batch: {len(batch)=}, {response=}",
        )


def make_user_timezone_log_query(
    batch: List[_Timezone], now: float
) -> Tuple[str, list]:
    query = io.StringIO()
    query.write(
        "WITH batch(sub, utzl_uid, timezone, style, guessed) AS (VALUES (?, ?, ?, ?, ?)"
    )
    for _ in range(len(batch) - 1):
        query.write(", (?, ?, ?, ?, ?)")

    query.write(
        ") INSERT INTO user_timezone_log ("
        " uid, user_id, timezone, source, style, guessed, created_at"
        ") "
        "SELECT"
        " batch.utzl_uid,"
        " users.id,"
        " batch.timezone,"
        " 'migration',"
        " batch.style,"
        " batch.guessed,"
        " ? "
        "FROM batch "
        "JOIN users ON users.sub = batch.sub"
    )

    return (
        query.getvalue(),
        [
            *(
                v
                for tz in batch
                for v in (
                    tz.user_sub,
                    tz.utzl_uid,
                    tz.timezone,
                    tz.style,
                    int(tz.guessed),
                )
            ),
            now,
        ],
    )
