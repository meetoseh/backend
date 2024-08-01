import gzip
import secrets
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from error_middleware import handle_warning
from journeys.lib.notifs import on_entering_lobby
from lib.client_flows.executor import (
    ClientScreenQueuePeekInfo,
    TrustedTrigger,
    execute_peek,
    execute_pop,
)
from lib.journals.journal_entry_item_data import (
    JournalEntryItemData,
    JournalEntryItemDataDataUI,
    JournalEntryItemUIConceptualUpgrade,
    JournalEntryItemUIConceptualUserJourney,
    JournalEntryItemUIFlow,
)
from lib.journals.master_keys import (
    get_journal_master_key_for_decryption,
    get_journal_master_key_for_encryption,
)
from models import STANDARD_ERRORS_BY_CODE
from typing import Annotated, Literal, Optional, Union, cast
from itgs import Itgs
import auth as std_auth
import unix_dates
from users.lib.streak import purge_user_streak_cache
from users.lib.timezones import get_user_timezone
import users.me.screens.auth
import users.lib.entitlements
from users.me.screens.lib.realize_screens import realize_screens
from users.me.screens.models.peeked_screen import PeekScreenResponse
from visitors.lib.get_or_create_visitor import VisitorSource
from dataclasses import dataclass
import journals.entry_auth
from loguru import logger

router = APIRouter()


class PopToJournalChatClassParameters(BaseModel):
    journal_entry_uid: str = Field(
        description="The UID of the journal entry the journey link is in"
    )
    journal_entry_jwt: str = Field(
        description="The JWT that shows you can access the journal entry"
    )
    entry_counter: int = Field(
        description="Which item within the entry contains the link"
    )
    journey_uid: str = Field(description="The UID of the journey within the link")
    upgrade_slug: Literal["journal_upgrade_for_journey"] = Field(
        description="The slug of the client flow to trigger if the user doesn't have access"
    )


class PopToJournalChatClassParametersTriggerRequest(BaseModel):
    slug: str = Field(
        description="The slug of the client flow to trigger, assuming the user has access"
    )
    parameters: PopToJournalChatClassParameters = Field(
        description="The parameters to convert"
    )


class PopToJournalChatClassRequest(BaseModel):
    screen_jwt: str = Field(description="The JWT which lets you pop the screen")
    trigger: PopToJournalChatClassParametersTriggerRequest = Field(
        description=(
            "The client flow to trigger with server parameters set with the journey and journal entry"
        ),
    )


@router.post(
    "/pop_to_journal_chat_class",
    response_model=PeekScreenResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def pop_screen_to_journal_chat_class(
    args: PopToJournalChatClassRequest,
    platform: VisitorSource,
    version: Optional[int] = None,
    visitor: Annotated[Optional[str], Header()] = None,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """A specialized pop endpoint which can be used to start a class linked within
    a journal chat, or to go to an upgrade screen if the user doesn't have access.

    Requires standard authorization for a user.
    """
    async with Itgs() as itgs:
        std_auth_result = await std_auth.auth_any(itgs, authorization)
        if std_auth_result.result is None:
            return std_auth_result.error_response

        user_sub = std_auth_result.result.sub

        async def _realize(screen: ClientScreenQueuePeekInfo):
            result = await realize_screens(
                itgs,
                user_sub=user_sub,
                platform=platform,
                visitor=visitor,
                result=screen,
            )

            return Response(
                content=result.__pydantic_serializer__.to_json(result),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=200,
            )

        screen_auth_result = await users.me.screens.auth.auth_any(
            itgs, args.screen_jwt, prefix=None
        )

        if screen_auth_result.result is None:
            logger.warning("journal chat class pop: screen auth failed")
            screen = await execute_peek(
                itgs,
                user_sub=std_auth_result.result.sub,
                platform=platform,
                version=version,
                trigger=TrustedTrigger(
                    flow_slug="error_bad_auth",
                    client_parameters={},
                    server_parameters={},
                ),
            )
            return await _realize(screen)

        entry_auth_result = await journals.entry_auth.auth_any(
            itgs, f"bearer {args.trigger.parameters.journal_entry_jwt}"
        )
        if (
            entry_auth_result.result is None
            or entry_auth_result.result.journal_entry_uid
            != args.trigger.parameters.journal_entry_uid
            or entry_auth_result.result.user_sub != user_sub
        ):
            logger.warning(
                f"journal chat class pop: journal entry auth failed ({entry_auth_result})"
            )
            screen = await execute_peek(
                itgs,
                user_sub=std_auth_result.result.sub,
                platform=platform,
                version=version,
                trigger=TrustedTrigger(
                    flow_slug="error_bad_auth",
                    client_parameters={},
                    server_parameters={},
                ),
            )
            return await _realize(screen)

        lookup_result = await get_journal_chat_class_link(
            itgs,
            user_sub=std_auth_result.result.sub,
            journal_entry_uid=args.trigger.parameters.journal_entry_uid,
            entry_counter=args.trigger.parameters.entry_counter,
            journey_uid=args.trigger.parameters.journey_uid,
            consistency="none",
        )
        if lookup_result.type == "not_found":
            logger.warning("journal chat class pop: lookup result not found at none")
            lookup_result = await get_journal_chat_class_link(
                itgs,
                user_sub=std_auth_result.result.sub,
                journal_entry_uid=args.trigger.parameters.journal_entry_uid,
                entry_counter=args.trigger.parameters.entry_counter,
                journey_uid=args.trigger.parameters.journey_uid,
                consistency="weak",
            )

        if lookup_result.type == "decryption_error":
            logger.warning("journal chat class pop: decryption error")
            await handle_warning(
                f"{__name__}:decryption_error",
                f"Failed to decrypt journal entry for {user_sub}: {lookup_result.subtype}",
            )
            screen = await execute_peek(
                itgs,
                user_sub=std_auth_result.result.sub,
                platform=platform,
                version=version,
                trigger=TrustedTrigger(
                    flow_slug="error_contact_support",
                    client_parameters={},
                    server_parameters={},
                ),
            )
            return await _realize(screen)

        if lookup_result.type != "found":
            logger.warning(
                f"journal chat class pop: lookup failed ({lookup_result.type})"
            )
            screen = await execute_peek(
                itgs,
                user_sub=std_auth_result.result.sub,
                platform=platform,
                version=version,
                trigger=TrustedTrigger(
                    flow_slug="error_bad_auth",
                    client_parameters={},
                    server_parameters={},
                ),
            )
            return await _realize(screen)

        trigger = args.trigger.slug
        trigger_type = "take"
        if lookup_result.is_pro:
            pro_entitlement = await users.lib.entitlements.get_entitlement(
                itgs, user_sub=std_auth_result.result.sub, identifier="pro"
            )
            if pro_entitlement is None or not pro_entitlement.is_active:
                logger.debug("journal chat class pop: not pro but needs to be")
                trigger = args.trigger.parameters.upgrade_slug
                trigger_type = "upgrade"

        store_result = await store_class_started_and_ui_entry(
            itgs,
            user_sub=std_auth_result.result.sub,
            journal_entry_uid=args.trigger.parameters.journal_entry_uid,
            journey_uid=args.trigger.parameters.journey_uid,
            type=trigger_type,
            trigger=trigger,
        )
        if store_result.type != "success":
            logger.warning(
                f"journal chat class pop: store failed ({store_result.type})"
            )
            await handle_warning(
                f"{__name__}:store_ui_entry",
                f"Failed to store UI entry for {user_sub}: {store_result.type}",
            )
            screen = await execute_peek(
                itgs,
                user_sub=std_auth_result.result.sub,
                platform=platform,
                version=version,
                trigger=TrustedTrigger(
                    flow_slug="error_contact_support",
                    client_parameters={},
                    server_parameters={},
                ),
            )
            return await _realize(screen)

        await on_entering_lobby(
            itgs,
            user_sub=std_auth_result.result.sub,
            journey_uid=lookup_result.journey_uid,
            action=f"starting the `{trigger}` flow from a link in their journal",
        )
        screen = await execute_pop(
            itgs,
            user_sub=std_auth_result.result.sub,
            platform=platform,
            version=version,
            expected_front_uid=screen_auth_result.result.user_client_screen_uid,
            trigger=(
                TrustedTrigger(
                    flow_slug=trigger,
                    client_parameters={},
                    server_parameters={
                        "journey": lookup_result.journey_uid,
                        "journal_entry": args.trigger.parameters.journal_entry_uid,
                    },
                )
            ),
        )
        return await _realize(screen)


@dataclass
class JournalChatClassLinkResultNotFound:
    type: Literal["not_found"]
    """
    - `not_found`: there was no corresponding link
    """


@dataclass
class JournalChatClassLinkResultFound:
    type: Literal["found"]
    """
    - `found`: the link was found
    """
    journey_uid: str
    """The UID of the journey in the link"""
    is_pro: bool
    """True if the class requires a pro subscription, false otherwise"""


@dataclass
class JournalChatClassLinkResultDecryptionError:
    type: Literal["decryption_error"]
    """
    - `decryption_error`: was unable to decrypt the entry
    """
    subtype: Literal["get_master_key", "decrypt_entry", "parse_entry"]
    """Where the error occurred"""


JournalChatClassLinkResult = Union[
    JournalChatClassLinkResultNotFound,
    JournalChatClassLinkResultFound,
    JournalChatClassLinkResultDecryptionError,
]


async def get_journal_chat_class_link(
    itgs: Itgs,
    /,
    *,
    user_sub: str,
    journal_entry_uid: str,
    entry_counter: int,
    consistency: Literal["strong", "weak", "none"],
    journey_uid: str,
) -> JournalChatClassLinkResult:
    conn = await itgs.conn()
    cursor = conn.cursor(consistency)

    response = await cursor.executeunified3(
        (
            (
                """
SELECT
    user_journal_master_keys.uid,
    journal_entry_items.master_encrypted_data
FROM users, journal_entries, journal_entry_items, user_journal_master_keys
WHERE
    users.sub = ?
    AND journal_entries.user_id = users.id
    AND journal_entries.uid = ?
    AND journal_entry_items.journal_entry_id = journal_entries.id
    AND journal_entry_items.entry_counter = ?
    AND journal_entry_items.user_journal_master_key_id = user_journal_master_keys.id
    AND user_journal_master_keys.user_id = users.id
                """,
                (
                    user_sub,
                    journal_entry_uid,
                    entry_counter,
                ),
            ),
            (
                """
SELECT
    EXISTS (
        SELECT 1 FROM courses, course_journeys
        WHERE
            (courses.flags & 256) <> 0
            AND courses.id = course_journeys.course_id
            AND course_journeys.journey_id = journeys.id
    ) AS b1,
    EXISTS (
        SELECT 1 FROM courses, course_journeys
        WHERE
            (courses.flags & 128) = 0
            AND courses.id = course_journeys.course_id
            AND course_journeys.journey_id = journeys.id
    ) AS b2
FROM journeys WHERE uid=?
                """,
                (journey_uid,),
            ),
        )
    )

    if not response[0].results or not response[1].results:
        return JournalChatClassLinkResultNotFound(type="not_found")

    is_pro = bool(response[1].results[0][0]) or bool(response[1].results[0][1])

    master_key_uid = cast(str, response[0].results[0][0])
    encrypted_data_token = cast(str, response[0].results[0][1])

    master_key = await get_journal_master_key_for_decryption(
        itgs,
        user_sub=user_sub,
        journal_master_key_uid=master_key_uid,
    )
    if master_key.type != "success":
        await handle_warning(
            f"{__name__}:get_journal_master_key_for_decryption",
            f"Failed to get journal master key for {user_sub}: {master_key.type}",
        )
        return JournalChatClassLinkResultDecryptionError(
            type="decryption_error",
            subtype="get_master_key",
        )

    try:
        decrypted_data = master_key.journal_master_key.decrypt(
            encrypted_data_token, ttl=None
        )
    except Exception as e:
        await handle_warning(
            f"{__name__}:decrypt_entry",
            f"Failed to decrypt journal entry for {user_sub}",
            exc=e,
        )
        return JournalChatClassLinkResultDecryptionError(
            type="decryption_error",
            subtype="decrypt_entry",
        )

    try:
        data = JournalEntryItemData.model_validate_json(gzip.decompress(decrypted_data))
    except Exception as e:
        await handle_warning(
            f"{__name__}:parse_entry",
            f"Failed to parse journal entry for {user_sub}",
            exc=e,
        )
        return JournalChatClassLinkResultDecryptionError(
            type="decryption_error",
            subtype="parse_entry",
        )

    if data.data.type != "textual":
        return JournalChatClassLinkResultNotFound(type="not_found")

    for part in data.data.parts:
        if part.type == "journey" and part.uid == journey_uid:
            return JournalChatClassLinkResultFound(
                type="found", journey_uid=journey_uid, is_pro=is_pro
            )

    return JournalChatClassLinkResultNotFound(type="not_found")


@dataclass
class JournalChatStoreUIEntryResultSuccess:
    type: Literal["success"]
    """
    - `success`: the entry was stored successfully
    """
    journal_entry_uid: str
    """The UID of the journal entry"""
    journal_entry_item_uid: str
    """The UID of the new journal entry item"""
    entry_counter: int
    """The counter of the new journal entry item"""


@dataclass
class JournalChatStoreUIEntryResultEncryptionError:
    type: Literal["encryption_error"]
    """
    - `encryption_error`: was unable to encrypt the entry
    """
    subtype: Literal["get_master_key"]


@dataclass
class JournalChatStoreUIEntryResultSaveError:
    type: Literal["save_error"]
    """
    - `save_error`: was unable to save the entry in the database
    """
    subtype: Literal["user_journey", "journal_entry_item"]


JournalChatStoreUIEntryResult = Union[
    JournalChatStoreUIEntryResultSuccess,
    JournalChatStoreUIEntryResultEncryptionError,
    JournalChatStoreUIEntryResultSaveError,
]


async def store_class_started_and_ui_entry(
    itgs: Itgs,
    /,
    *,
    user_sub: str,
    journal_entry_uid: str,
    journey_uid: str,
    type: Literal["upgrade", "take"],
    trigger: str,
) -> JournalChatStoreUIEntryResult:
    entry_at = time.time()
    user_tz = await get_user_timezone(itgs, user_sub=user_sub)
    entry_unix_date_in_user_tz = unix_dates.unix_timestamp_to_unix_date(
        entry_at, tz=user_tz
    )

    conn = await itgs.conn()
    cursor = conn.cursor()
    if type == "take":
        user_journey_uid = f"oseh_uj_{secrets.token_urlsafe(16)}"
        response = await cursor.executeunified3(
            (
                (
                    """
SELECT 1 FROM users, user_journeys
WHERE
    users.sub = ?
    AND user_journeys.user_id = users.id
    AND user_journeys.created_at_unix_date = ?
LIMIT 1
                    """,
                    (user_sub, entry_unix_date_in_user_tz),
                ),
                (
                    """
INSERT INTO user_journeys (
    uid, user_id, journey_id, created_at, created_at_unix_date
)
SELECT
    ?, users.id, journeys.id, ?, ?
FROM users, journeys
WHERE
    users.sub = ?
    AND journeys.uid = ?
                    """,
                    (
                        user_journey_uid,
                        entry_at,
                        entry_unix_date_in_user_tz,
                        user_sub,
                        journey_uid,
                    ),
                ),
            ),
            read_consistency="strong",
        )
        if response[1].rows_affected is None or response[1].rows_affected < 1:
            return JournalChatStoreUIEntryResultSaveError(
                type="save_error", subtype="user_journey"
            )
        if response[1].rows_affected != 1:
            await handle_warning(
                f"{__name__}:store_ui_entry",
                f"Wrong number of rows affected when inserting user journey for {user_sub}: {response[1].rows_affected}",
            )
        if not response[0].results:
            await purge_user_streak_cache(itgs, sub=user_sub)

    master_key = await get_journal_master_key_for_encryption(
        itgs, user_sub=user_sub, now=entry_at
    )
    if master_key.type != "success":
        if type == "take":
            await cursor.execute(
                "DELETE FROM user_journeys WHERE uid=?", (user_journey_uid,)
            )
            await purge_user_streak_cache(itgs, sub=user_sub)

        return JournalChatStoreUIEntryResultEncryptionError(
            type="encryption_error", subtype="get_master_key"
        )

    encrypted_data = master_key.journal_master_key.encrypt_at_time(
        gzip.compress(
            JournalEntryItemData.__pydantic_serializer__.to_json(
                JournalEntryItemData(
                    display_author="self",
                    type="ui",
                    data=JournalEntryItemDataDataUI(
                        conceptually=(
                            JournalEntryItemUIConceptualUserJourney(
                                journey_uid=journey_uid,
                                type="user_journey",
                                user_journey_uid=user_journey_uid,
                            )
                            if type == "take"
                            else JournalEntryItemUIConceptualUpgrade(type="upgrade")
                        ),
                        flow=JournalEntryItemUIFlow(slug=trigger),
                        type="ui",
                    ),
                )
            ),
            mtime=0,
        ),
        int(entry_at),
    ).decode("ascii")

    journal_entry_item_uid = f"oseh_jei_{secrets.token_urlsafe(16)}"
    response = await cursor.executeunified3(
        (
            (
                """
INSERT INTO journal_entry_items (
    uid,
    journal_entry_id,
    entry_counter,
    user_journal_master_key_id,
    master_encrypted_data,
    created_at,
    created_unix_date
)
SELECT
    ?,
    journal_entries.id,
    (SELECT MAX(jei.entry_counter) + 1 FROM journal_entry_items AS jei WHERE jei.journal_entry_id = journal_entries.id),
    user_journal_master_keys.id,
    ?,
    ?,
    ?
FROM users, journal_entries, user_journal_master_keys
WHERE
    users.sub = ?
    AND journal_entries.user_id = users.id
    AND journal_entries.uid = ?
    AND user_journal_master_keys.user_id = users.id
    AND user_journal_master_keys.uid = ?
                """,
                (
                    journal_entry_item_uid,
                    encrypted_data,
                    entry_at,
                    entry_unix_date_in_user_tz,
                    user_sub,
                    journal_entry_uid,
                    master_key.journal_master_key_uid,
                ),
            ),
            (
                "SELECT entry_counter FROM journal_entry_items WHERE uid=?",
                (journal_entry_item_uid,),
            ),
        ),
        read_consistency="strong",
    )
    if response[0].rows_affected is None or response[0].rows_affected < 1:
        if type == "take":
            await cursor.execute(
                "DELETE FROM user_journeys WHERE uid=?", (user_journey_uid,)
            )
            await purge_user_streak_cache(itgs, sub=user_sub)

        assert not response[1].results, response

        return JournalChatStoreUIEntryResultSaveError(
            type="save_error", subtype="journal_entry_item"
        )

    if response[0].rows_affected != 1:
        await handle_warning(
            f"{__name__}:store_ui_entry",
            f"Wrong number of rows affected when inserting journal entry item for {user_sub}: {response[0].rows_affected}",
        )

    assert response[1].results, response
    entry_counter = cast(int, response[1].results[0][0])

    return JournalChatStoreUIEntryResultSuccess(
        type="success",
        journal_entry_uid=journal_entry_uid,
        journal_entry_item_uid=journal_entry_item_uid,
        entry_counter=entry_counter,
    )
