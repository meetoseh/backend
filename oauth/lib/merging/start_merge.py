import json
import secrets
import time
import traceback
from typing import (
    Any,
    Dict,
    List,
    Literal,
    Mapping,
    Optional,
    Sequence,
    Set,
    Tuple,
    cast,
)
from typing_extensions import TypedDict
import anyio
from pydantic import BaseModel, Field, TypeAdapter
from admin.logs.routes.read_daily_reminder_settings_log import (
    interpret_day_of_week_mask,
)
from error_middleware import handle_error
from file_service import AsyncWritableBytesIO
from itgs import Itgs
import auth as std_auth
from lib.daily_reminders.setting_stats import DailyReminderTimeRange
from lib.redis_stats_preparer import RedisStatsPreparer
from oauth.lib.merging.core import create_merging_queries
from oauth.lib.merging.operation_order import OperationOrder
from oauth.lib.merging.query import MergeContext, MergeQuery
import oauth.lib.merging.start_merge_auth as start_merge_auth
import oauth.lib.merging.confirm_merge_auth as confirm_merge_auth
from users.lib.entitlements import get_entitlement
from users.me.routes.read_daily_reminder_settings import (
    EMAIL_PREFERRED_CHANNELS,
    SMS_PREFERRED_CHANNELS,
    RealDailyReminderChannelSettings,
    get_implied_settings,
)
from users.me.routes.read_merge_account_suggestions import MergeProvider
from users.me.routes.update_notification_time import DayOfWeek
from oauth.lib.merging.log import MergeFreeformLog, merge_freeform_log
from functools import partial
import os
import socket
from rqdb.result import BulkResult


class EmailForConflict(BaseModel):
    email_address: str = Field(description="The email address")
    suppressed: bool = Field(
        description="If true, we cannot send emails to this address due to e.g. a past complaint"
    )
    verified: bool = Field(
        description="If true, we are satisfied that the user has access to this email address"
    )
    enabled: bool = Field(
        description="If true, the user is ok receiving emails at this address"
    )


class PhoneForConflict(BaseModel):
    phone_number: str = Field(description="The phone number")
    suppressed: bool = Field(
        description="If true, we cannot send SMS to this number due to e.g. a Stop message"
    )
    verified: bool = Field(
        description="If true, we are satisfied that the user has access to this phone number"
    )
    enabled: bool = Field(
        description="If true, the user is ok receiving SMS at this number"
    )


class DailyReminderSettingsForConflict(BaseModel):
    days_of_week: List[DayOfWeek] = Field(
        description="the days of the week they receive notifications on this channel",
        max_length=7,
    )
    start_time: int = Field(
        description="The earliest they receive notifications in seconds from midnight"
    )
    end_time: int = Field(
        description="The latest they receive notifications in seconds from midnight"
    )


class OauthEmailConflictInfo(BaseModel):
    original: List[EmailForConflict] = Field(
        description="The emails associated with the original user"
    )
    merging: List[EmailForConflict] = Field(
        description="The emails associated with the merging user"
    )
    original_settings: DailyReminderSettingsForConflict = Field(
        description="The notification settings for the original user"
    )
    merging_settings: DailyReminderSettingsForConflict = Field(
        description="The notification settings for the merging user"
    )


class OauthPhoneConflictInfo(BaseModel):
    original: List[PhoneForConflict] = Field(
        description="The phones associated with the original user"
    )
    merging: List[PhoneForConflict] = Field(
        description="The phones associated with the merging user"
    )
    original_settings: DailyReminderSettingsForConflict = Field(
        description="The notification settings for the original user"
    )
    merging_settings: DailyReminderSettingsForConflict = Field(
        description="The notification settings for the merging user"
    )


class OauthMergeConfirmationRequiredDetails(BaseModel):
    email: Optional[OauthEmailConflictInfo] = Field(
        description=(
            "The email conflict which need to be resolved. An email conflict "
            "is when both accounts are receiving email notifications, since the "
            "user probably only wants to receive notifications at one address. "
            "When the user confirms the merge they will need to select which email "
            "addresses should remain enabled."
        )
    )
    phone: Optional[OauthPhoneConflictInfo] = Field(
        description=(
            "The phone conflict which need to be resolved. A phone conflict "
            "is when both accounts are receiving SMS notifications, since the "
            "user probably only wants to receive notifications at one number. "
            "When the user confirms the merge they will need to select which phone "
            "numbers should remain enabled."
        )
    )
    merge_jwt: str = Field(
        description="The new merge JWT to use for the confirm_merge request."
    )


class LoginOption(BaseModel):
    provider: MergeProvider = Field(
        description="The identity provider. Dev is only available in development mode"
    )


class OauthMergeResult(BaseModel):
    result: Literal[
        "no_change_required",
        "created_and_attached",
        "trivial_merge",
        "confirmation_required",
        "original_user_deleted",
    ] = Field(
        description=(
            "What action was taken immediately. The possibilities are:\n"
            "- `no_change_required`: the code was associated with a user identity already associated"
            " with the original user. For example, the user just tried to merge with the same identity"
            " they signed in with.\n"
            "- `created_and_attached`: the code corresponded to a provider sub that we didn't recognize,"
            " i.e., if this were the login flow we would have created a user. Instead of creating a user,"
            " we created a new user identity associating this provider sub with the original user.\n"
            "- `trivial_merge`: the code corresponded to a provider sub that we did recognize, and it was"
            " a different user than the original user that started the merge. However, one of the accounts"
            " had essentially no information, so we just merged the two accounts together.\n"
            "- `confirmation_required`: the code corresponded to a provider sub that we did recognize, and"
            " it was a different user than the original user that started the merge. There is nothing blocking"
            " a merge of the two accounts, but the merge may be destructive. The user needs to confirm which"
            " account we should prefer when information conflicts.\n"
            "- `original_user_deleted`: the user with the provided JWT has since been deleted"
        )
    )
    conflict_details: Optional[OauthMergeConfirmationRequiredDetails] = Field(
        None,
        description=(
            "If the `result` is `confirmation_required`, this field will be populated with"
            " details about the conflict that the user needs to resolve"
        ),
    )
    original_login_options: List[LoginOption] = Field(
        description=(
            "The login methods available on the original user (before this did anything), "
            "to help explain how they will be able to login after the merge"
        )
    )
    merging_login_options: List[LoginOption] = Field(
        description=(
            "The login methods available on the merging user "
            "(before they were merged, for `trivial_merge`). For "
            "`created_and_attached`, this will be the newly referenced provider. "
            "For `no_change_required` and `original_user_deleted`, this will be empty. "
        )
    )


async def attempt_start_merge(
    itgs: Itgs,
    *,
    original_user: std_auth.SuccessfulAuthResult,
    merge: start_merge_auth.SuccessfulAuthResult,
) -> OauthMergeResult:
    """Performs the initial merge for the given original user authorized to perform
    the given merge.

    Args:
        itgs (Itgs): the integrations to (re)use
        original_user (std_auth.SuccessfulAuthResult): The user must provide valid
            authorization for the original user in the merge along with the merge
            JWT to avoid merge JWTs extending the duration of id tokens, which is
            not intended. This is the result of the standard auth flow.
        merge (oauth.lib.start_merge_auth.SuccessfulAuthResult): The user must provide
            proof they are allowed to perform the given merge. We will also use this
            for ensuring the example claims of the provider for the user identity are
            properly updated/initialized

    Returns:
        OauthMergeResult: The result of the operation
    """
    merge_at = time.time()
    operation_uid = f"oseh_mal_o_{secrets.token_urlsafe(16)}"
    mal_duplicate_identity = f"oseh_mal_{secrets.token_urlsafe(16)}"
    mal_create_identity = f"oseh_mal_{secrets.token_urlsafe(16)}"
    mal_transfer_identity = f"oseh_mal_{secrets.token_urlsafe(16)}"
    merge_provider = cast(
        Literal["Direct", "Google", "SignInWithApple", "Passkey", "Silent", "Dev"],
        merge.provider,
    )

    async with merge_freeform_log(itgs, operation_uid=operation_uid) as log:
        await log.out.write(
            b"---LOG START---\n"
            b"Action: attempt_start_merge\n"
            b"Environment:\n"
            b"  " + os.environ["ENVIRONMENT"].encode("utf-8") + b"\n"
            b"  socket.gethostname() = " + socket.gethostname().encode("utf-8") + b"\n"
            b"Parameters:\n"
            b"  original_user:\n"
            b"    sub: " + original_user.sub.encode("utf-8") + b"\n"
            b"    claims:\n    "
            + "\n    ".join(
                json.dumps(original_user.claims, indent=2).splitlines(keepends=False)
            ).encode("utf-8")
            + b"\n"
            b"  merge:\n"
            b"    provider: " + merge.provider.encode("utf-8") + b"\n"
            b"    provider_sub: " + merge.provider_sub.encode("utf-8") + b"\n"
            b"    provider_claims:\n    "
            + "\n    ".join(
                json.dumps(merge.provider_claims, indent=2).splitlines(keepends=False)
            ).encode("utf-8")
            + b"\n"
            b"    claims:\n    "
            + "\n    ".join(
                json.dumps(merge.claims, indent=2).splitlines(keepends=False)
            ).encode("utf-8")
            + b"\n\n"
            b"Top-level computed values:\n"
            b"  merge_at=" + str(merge_at).encode("ascii") + b"\n"
            b"  operation_uid=" + operation_uid.encode("ascii") + b"\n"
            b"  mal_duplicate_identity="
            + mal_duplicate_identity.encode("ascii")
            + b"\n"
            b"  mal_create_identity=" + mal_create_identity.encode("ascii") + b"\n"
            b"  mal_transfer_identity=" + mal_transfer_identity.encode("ascii") + b"\n"
            b"\n\n"
            b"---Initializing Queries---\n"
        )
        queries: List[MergeQuery] = [
            *await create_duplicate_identity_query(
                itgs,
                operation_uid=operation_uid,
                original_user_sub=original_user.sub,
                merging_provider=merge_provider,
                merging_provider_sub=merge.provider_sub,
                log=log,
                merge_at=merge_at,
                mal_duplicate_identity=mal_duplicate_identity,
            ),
            *await create_create_identity_query(
                itgs,
                operation_uid=operation_uid,
                original_user_sub=original_user.sub,
                merging_provider=merge_provider,
                merging_provider_sub=merge.provider_sub,
                merging_provider_claims=merge.provider_claims,
                log=log,
                merge_at=merge_at,
                mal_create_identity=mal_create_identity,
            ),
            *await create_transfer_identity_query(
                itgs,
                operation_uid=operation_uid,
                original_user_sub=original_user.sub,
                merging_provider=merge_provider,
                merging_provider_sub=merge.provider_sub,
                log=log,
                merge_at=merge_at,
                mal_transfer_identity=mal_transfer_identity,
            ),
            *await create_merging_queries(
                itgs,
                confirm_log_uid=mal_transfer_identity,
                confirm_required_step_result="trivial",
                operation_uid=operation_uid,
                original_user_sub=original_user.sub,
                merging_provider=merge_provider,
                merging_provider_sub=merge.provider_sub,
                log=log.out,
                merge_at=merge_at,
                email_hint=None,
                phone_hint=None,
            ),
        ]
        await log.out.write(b"\n\n---QUERIES---\n")

        for idx, query in enumerate(queries):
            await log.out.write(
                b"--- "
                + str(idx).encode("ascii")
                + b" ---\n"
                + query.query.encode("utf-8")
                + b"\n"
                + json.dumps(query.qargs, indent=2).encode("utf-8")
                + b"\n\n"
            )

        await log.out.write(b"\n\n---EXECUTING QUERIES---\n")

        started_executing_at = time.perf_counter()
        async with Itgs() as itgs2:
            # temporary workaround to increase timeout for this query
            conn2 = await itgs2.conn()
            conn2.timeout = 600
            cursor2 = conn2.cursor()

            # testing performance
            result_items = []
            for idx, q in enumerate(queries):
                start_at = time.perf_counter()
                result_item = await cursor2.execute(
                    q.query, q.qargs, raise_on_error=False
                )
                end_at = time.perf_counter()
                await log.out.write(
                    b"--- " + str(idx).encode("ascii") + b" ---\n"
                    b"  execution time: "
                    + f"{end_at - start_at:.3f}".encode("ascii")
                    + b"s\n"
                )
                result_items.append(result_item)
                if result_item.error is not None:
                    break

            # result = await cursor2.executemany2(
            #     [q.query for q in queries],
            #     [q.qargs for q in queries],
            #     raise_on_error=False,
            # )
            result = BulkResult(result_items)
        execution_time = time.perf_counter() - started_executing_at
        await log.out.write(
            b"execution time: " + f"{execution_time:.3f}".encode("ascii") + b"s\n"
        )

        for idx, item in enumerate(result):
            await log.out.write(
                b"--- " + str(idx).encode("ascii") + b" ---\n"
                b"  rows affected: "
                + str(item.rows_affected).encode("ascii")
                + b"\n"
                + b"  error: "
                + str(item.error).encode("ascii")
                + b"\n"
            )

        result.raise_on_error()

        await log.out.write(b"\n\n---CHECKING RESULTS---\n")
        try:
            merge_result = await get_merge_result(
                itgs,
                mal_duplicate_identity=mal_duplicate_identity,
                mal_create_identity=mal_create_identity,
                mal_transfer_identity=mal_transfer_identity,
                operation_uid=operation_uid,
                original_user=original_user,
                merge=merge,
                log=log.out,
            )
        except Exception as exc:
            await log.out.write(
                b"\nCAUGHT ERROR\n"
                + str(exc).encode("utf-8")
                + b"\n"
                + "\n".join(
                    traceback.format_exception(type(exc), exc, exc.__traceback__)
                ).encode("utf-8")
            )
            await handle_error(
                exc, extra_info="while getting merge result (will re-raise exception)"
            )
            raise exc
        merging_expected = merge_result.result == "trivial_merge"
        await log.out.write(
            b"merge_result:\n"
            + merge_result.__pydantic_serializer__.to_json(merge_result, indent=2)
            + b"\ncomputed:\n"
            b"merging_expected: " + str(merging_expected).encode("ascii") + b"\n"
        )
        await log.out.write(b"\n\n---HANDLERS---\n")

        last_err = None
        stats = RedisStatsPreparer()
        for idx, (query, item) in enumerate(zip(queries, result)):
            await log.out.write(b"--- " + str(idx).encode("ascii") + b" ---\n")
            try:
                await query.handler(
                    MergeContext(
                        result=item,
                        merging_expected=merging_expected,
                        stats=stats,
                        log=log.out,
                    )
                )
            except Exception as exc:
                await log.out.write(
                    b"\nCAUGHT ERROR\n"
                    + str(exc).encode("utf-8")
                    + b"\n"
                    + "\n".join(
                        traceback.format_exception(type(exc), exc, exc.__traceback__)
                    ).encode("utf-8")
                )
                await handle_error(exc, extra_info=f"{idx=}")
                last_err = exc

        await log.out.write(b"\n\n--RESTORING PURCHASES--\n")
        pro_entitlement = await get_entitlement(
            itgs, user_sub=original_user.sub, identifier="pro", force=True
        )
        if pro_entitlement is None:
            await log.out.write(b"pro entitlement is None\n")
        else:
            await log.out.write(b"pro entitlement found:\n")
            await log.out.write(
                pro_entitlement.__pydantic_serializer__.to_json(
                    pro_entitlement, indent=2
                )
            )
            await log.out.write(b"\n")

        await log.out.write(b"\n\n---STORING STATS---\n")
        await log.out.write(b"stats:\n{\n")
        for key, val in stats.stats.items():
            await log.out.write(b'  b"' + key + b"': {\n")
            for subkey, subval in val.items():
                # we will keep trailing commas since this isn't valid json anyway
                await log.out.write(
                    b'    b"' + subkey + b'": ' + str(subval).encode("ascii") + b",\n"
                )
            await log.out.write(b"  },\n")
        await log.out.write(b"}\n\n")
        await log.out.write(b"earliest_keys:\n{\n")
        for key, val in stats.earliest_keys.items():
            await log.out.write(
                b'  b"' + key + b'": ' + str(val).encode("ascii") + b",\n"
            )
        await log.out.write(b"}\n\n")

        start_storing_at = time.perf_counter()
        await stats.store(itgs)
        storing_time = time.perf_counter() - start_storing_at
        await log.out.write(
            b"storing time: " + f"{storing_time:.3f}".encode("ascii") + b"s\n"
        )

        await log.out.write(
            b"\n\n---DONE---\nend time: " + str(time.time()).encode("ascii") + b"\n"
        )

        if last_err is not None:
            await log.out.write(b"Raising last error\n")
            raise last_err

        await log.out.write(b"No errors\n")
        return merge_result


class _MovedUserIdentity(TypedDict):
    uid: str
    provider: MergeProvider
    sub: str


class _MoveUserIdentitiesReasonContext(TypedDict):
    rows: int
    merging: List[_MovedUserIdentity]


class _MoveUserIdentitiesReason(TypedDict):
    context: _MoveUserIdentitiesReasonContext


class _UserIdentityFromDB(TypedDict):
    provider: MergeProvider
    sub: str


login_options_adapter = cast(
    TypeAdapter[List[LoginOption]], TypeAdapter(List[LoginOption])
)


async def get_merge_result(
    itgs: Itgs,
    *,
    mal_duplicate_identity: str,
    mal_create_identity: str,
    mal_transfer_identity: str,
    operation_uid: str,
    original_user: std_auth.SuccessfulAuthResult,
    merge: start_merge_auth.SuccessfulAuthResult,
    log: AsyncWritableBytesIO,
) -> OauthMergeResult:
    """Checks the entries in the merge_account_log with the given uids to determine
    the oauth merge result
    """
    query: str = (
        "SELECT"
        " EXISTS (SELECT 1 FROM merge_account_log WHERE uid = ?) AS b1,"
        " EXISTS (SELECT 1 FROM merge_account_log WHERE uid = ?) AS b2,"
        " EXISTS (SELECT 1 FROM merge_account_log WHERE uid = ? AND step_result = 'trivial') AS b3,"
        " EXISTS (SELECT 1 FROM merge_account_log WHERE uid = ? AND step_result <> 'trivial') AS b4,"
        " (SELECT reason FROM merge_account_log WHERE operation_uid = ? AND phase = 'merging' AND step = 'move_user_identities'),"
        " ("
        "  SELECT"
        "   json_group_array("
        "    json_object("
        "     'provider', user_identities.provider"
        "     , 'sub', user_identities.sub"
        "    )"
        "   )"
        "  FROM user_identities, users"
        "  WHERE"
        "   user_identities.user_id = users.id"
        "   AND users.sub = ?"
        " ),"
        " ("
        "  SELECT"
        "   json_group_array("
        "    json_object("
        "     'provider', user_identities.provider"
        "     , 'sub', user_identities.sub"
        "    )"
        "   )"
        "  FROM user_identities, users AS merging_user"
        "  WHERE"
        "   user_identities.user_id = merging_user.id"
        "   AND merging_user.sub <> ?"
        "   AND EXISTS ("
        "    SELECT 1 FROM user_identities AS ui"
        "    WHERE"
        "     ui.user_id = merging_user.id"
        "     AND ui.provider = ?"
        "     AND ui.sub = ?"
        "   )"
        " )"
    )
    qargs: Sequence[Any] = (
        mal_duplicate_identity,
        mal_create_identity,
        mal_transfer_identity,
        mal_transfer_identity,
        operation_uid,
        original_user.sub,
        original_user.sub,
        merge.provider,
        merge.provider_sub,
    )
    await log.write(
        b"query:\n"
        + query.encode("utf-8")
        + b"\nqargs:\n"
        + json.dumps(qargs, indent=2).encode("utf-8")
        + b"\n"
    )

    conn = await itgs.conn()
    cursor = conn.cursor("weak")
    response = await cursor.execute(query, qargs, raise_on_error=False)
    await log.write(
        b"response @ weak:\n"
        b"  results:" + json.dumps(response.results).encode("utf-8") + b"\n"
        b"  error: " + str(response.error).encode("ascii") + b"\n"
    )
    response.raise_on_error()
    assert response.results, response
    was_duplicate_identity = bool(response.results[0][0])
    was_create_identity = bool(response.results[0][1])
    was_trivial_merge = bool(response.results[0][2])
    was_confirmation_required = bool(response.results[0][3])
    was_original_user_deleted = not any(
        (
            was_duplicate_identity,
            was_create_identity,
            was_trivial_merge,
            was_confirmation_required,
        )
    )
    move_user_identities_reason_raw = cast(Optional[str], response.results[0][4])
    current_user_identities_raw = cast(str, response.results[0][5])
    merging_user_identities_raw = cast(str, response.results[0][6])

    move_user_identities_reason = (
        None
        if move_user_identities_reason_raw is None
        else cast(
            _MoveUserIdentitiesReason, json.loads(move_user_identities_reason_raw)
        )
    )
    current_user_identities = cast(
        List[_UserIdentityFromDB], json.loads(current_user_identities_raw)
    )
    merging_user_identities = cast(
        List[_UserIdentityFromDB], json.loads(merging_user_identities_raw)
    )

    await log.write(
        b"interpreted:\n"
        b"  was_duplicate_identity: "
        + str(was_duplicate_identity).encode("ascii")
        + b"\n"
        b"  was_create_identity: " + str(was_create_identity).encode("ascii") + b"\n"
        b"  was_trivial_merge: " + str(was_trivial_merge).encode("ascii") + b"\n"
        b"  was_confirmation_required: "
        + str(was_confirmation_required).encode("ascii")
        + b"\n"
        b"  was_original_user_deleted: "
        + str(was_original_user_deleted).encode("ascii")
        + b"\n"
        b"  move_user_identities_reason: "
        + (
            b"None"
            if move_user_identities_reason is None
            else b"\n    "
            + "\n    ".join(
                json.dumps(move_user_identities_reason, indent=2).splitlines()
            ).encode("utf-8")
        )
        + b"\n"
        b"  current_user_identities:\n    "
        + (
            "\n    ".join(
                json.dumps(current_user_identities, indent=2).splitlines()
            ).encode("utf-8")
        )
        + b"\n"
        b"  merging_user_identities:\n    "
        + (
            "\n    ".join(
                json.dumps(merging_user_identities, indent=2).splitlines()
            ).encode("utf-8")
        )
        + b"\n"
    )

    current_login_options = [opt for opt in current_user_identities or []]
    still_existing_merging_login_options = [
        opt for opt in merging_user_identities or []
    ]
    moved_options: Set[Tuple[MergeProvider, str]] = (
        set(
            (
                (
                    opt["provider"],
                    opt["sub"],
                )
                for opt in move_user_identities_reason["context"]["merging"]
            )
        )
        if move_user_identities_reason is not None
        else set()
    )
    if not was_duplicate_identity:
        moved_options.add((merge.provider, merge.provider_sub))

    original_login_options = [
        LoginOption(
            provider=opt["provider"],
        )
        for opt in current_login_options
        if (opt["provider"], opt["sub"]) not in moved_options
    ]
    merging_login_options = [
        LoginOption(
            provider=opt["provider"],
        )
        for opt in current_login_options
        if (opt["provider"], opt["sub"]) in moved_options
    ]

    await log.write(
        b"  current_login_options:\n    "
        + (
            b"\n    ".join(
                json.dumps(current_login_options, indent=2).encode("utf-8").splitlines()
            )
        )
        + b"\n"
        b"  still_existing_merging_login_options:\n    "
        + (
            b"\n    ".join(
                json.dumps(still_existing_merging_login_options, indent=2)
                .encode("utf-8")
                .splitlines()
            )
        )
        + b"\n"
        b"  original_login_options:\n    "
        + (
            b"\n    ".join(
                login_options_adapter.dump_json(
                    original_login_options, indent=2
                ).splitlines()
            )
        )
        + b"\n"
        b"  merging_login_options:\n    "
        + (
            b"\n    ".join(
                LoginOption.__pydantic_serializer__.to_json(
                    merging_login_options, indent=2
                ).splitlines()
            )
        )
        + b"\n"
        b"  moved_options:\n    "
        + b"\n    ".join(
            json.dumps(list(moved_options), indent=2).encode("utf-8").splitlines()
        )
        + b"\n"
    )

    if was_duplicate_identity:
        return OauthMergeResult(
            result="no_change_required",
            conflict_details=None,
            original_login_options=original_login_options,
            merging_login_options=merging_login_options,
        )
    elif was_create_identity:
        return OauthMergeResult(
            result="created_and_attached",
            conflict_details=None,
            original_login_options=original_login_options,
            merging_login_options=merging_login_options,
        )
    elif was_trivial_merge:
        return OauthMergeResult(
            result="trivial_merge",
            conflict_details=None,
            original_login_options=original_login_options,
            merging_login_options=merging_login_options,
        )
    elif was_original_user_deleted:
        await log.write(b"\ndouble checking user is deleted\n")
        query = "SELECT 1 FROM users WHERE sub = ?"
        qargs = (original_user.sub,)
        await log.write(
            b"query:\n"
            + query.encode("utf-8")
            + b"\nqargs:\n"
            + json.dumps(qargs, indent=2).encode("utf-8")
            + b"\n"
        )
        response = await cursor.execute(query, qargs, raise_on_error=False)
        await log.write(
            b"response @ weak:\n"
            b"  results:" + json.dumps(response.results).encode("utf-8") + b"\n"
            b"  error: " + str(response.error).encode("ascii") + b"\n"
        )
        response.raise_on_error()
        assert not response.results, response
        return OauthMergeResult(
            result="original_user_deleted",
            conflict_details=None,
            original_login_options=original_login_options,
            merging_login_options=merging_login_options,
        )

    await log.write(b"\nchecking for confirmation details\n")

    query = "SELECT reason FROM merge_account_log WHERE uid=?"
    qargs = (mal_transfer_identity,)
    await log.write(
        b"query:\n"
        + query.encode("utf-8")
        + b"\nqargs:\n"
        + json.dumps(qargs, indent=2).encode("utf-8")
        + b"\n"
    )

    response = await cursor.execute(query, qargs, raise_on_error=False)
    await log.write(
        b"response @ weak:\n"
        b"  results:" + json.dumps(response.results).encode("utf-8") + b"\n"
        b"  error: " + str(response.error).encode("ascii") + b"\n"
    )
    response.raise_on_error()
    assert response.results, response
    reason_raw = response.results[0][0]
    reason_parsed = cast(dict, json.loads(reason_raw))

    await log.write(
        b"parsed reason:\n"
        + json.dumps(reason_parsed, indent=2).encode("utf-8")
        + b"\n"
    )

    email_conflict: Optional[OauthEmailConflictInfo] = None
    if reason_parsed["context"]["email"]["conflicts"]:
        await log.write(b" - fetching email conflict - \n")
        email_conflict = await get_email_conflict_info(
            itgs,
            original_user_sub=original_user.sub,
            merging_user_sub=reason_parsed["context"]["merging"]["user_sub"],
            log=log,
        )
        await log.write(b" - done fetching email conflict - \n")
        await log.write(
            b"email_conflict = "
            + email_conflict.__pydantic_serializer__.to_json(email_conflict, indent=2)
            + b"\n"
        )

    phone_conflict: Optional[OauthPhoneConflictInfo] = None
    if reason_parsed["context"]["phone"]["conflicts"]:
        await log.write(b" - fetching phone conflict - \n")
        phone_conflict = await get_phone_conflict_info(
            itgs,
            original_user_sub=original_user.sub,
            merging_user_sub=reason_parsed["context"]["merging"]["user_sub"],
            log=log,
        )
        await log.write(b" - done fetching phone conflict - \n")
        await log.write(
            b"phone_conflict = "
            + phone_conflict.__pydantic_serializer__.to_json(phone_conflict, indent=2)
            + b"\n"
        )

    assert phone_conflict or email_conflict, "no conflicts found"
    return OauthMergeResult(
        result="confirmation_required",
        conflict_details=OauthMergeConfirmationRequiredDetails(
            email=email_conflict,
            phone=phone_conflict,
            merge_jwt=await confirm_merge_auth.create_jwt(
                itgs,
                original_user_sub=original_user.sub,
                provider=merge.provider,
                provider_claims=merge.provider_claims,
                merging_user_sub=reason_parsed["context"]["merging"]["user_sub"],
                conflicts=confirm_merge_auth.ConfirmMergeConflicts(
                    email=not not email_conflict,
                    phone=not not phone_conflict,
                ),
            ),
        ),
        original_login_options=[
            LoginOption(
                provider=opt["provider"],
            )
            for opt in current_login_options
        ],
        merging_login_options=[
            LoginOption(
                provider=opt["provider"],
            )
            for opt in still_existing_merging_login_options
        ],
    )


async def get_email_conflict_info(
    itgs: Itgs,
    *,
    original_user_sub: str,
    merging_user_sub: str,
    log: AsyncWritableBytesIO,
) -> OauthEmailConflictInfo:
    """Assumes that there is an email conflict between the given users and fetches
    their email information from the database in order to form the response that
    will allow the user to resolve the conflict
    """
    query: str = (
        "SELECT"
        " users.sub,"
        " user_email_addresses.email,"
        " EXISTS (SELECT 1 FROM suppressed_emails WHERE suppressed_emails.email_address = user_email_addresses.email) AS suppressed,"
        " user_email_addresses.verified,"
        " user_email_addresses.receives_notifications "
        "FROM user_email_addresses, users "
        "WHERE"
        " user_email_addresses.user_id = users.id"
        " AND users.sub IN (?, ?)"
    )
    qargs: Sequence[Any] = (
        original_user_sub,
        merging_user_sub,
    )
    await log.write(
        b"query:\n"
        + query.encode("utf-8")
        + b"\nqargs:\n"
        + json.dumps(qargs, indent=2).encode("utf-8")
        + b"\n"
    )
    conn = await itgs.conn()
    cursor = conn.cursor("weak")
    response = await cursor.execute(query, qargs, raise_on_error=False)
    await log.write(
        b"response @ weak:\n"
        b"  results:" + json.dumps(response.results).encode("utf-8") + b"\n"
        b"  error: " + str(response.error).encode("ascii") + b"\n"
    )
    response.raise_on_error()

    original: List[EmailForConflict] = []
    merging: List[EmailForConflict] = []
    for row_sub, row_email, row_suppressed, row_verified, row_enabled in (
        response.results or []
    ):
        if row_sub == original_user_sub:
            original.append(
                EmailForConflict(
                    email_address=row_email,
                    suppressed=row_suppressed,
                    verified=row_verified,
                    enabled=row_enabled,
                )
            )
        elif row_sub == merging_user_sub:
            merging.append(
                EmailForConflict(
                    email_address=row_email,
                    suppressed=row_suppressed,
                    verified=row_verified,
                    enabled=row_enabled,
                )
            )
        else:
            raise Exception(f"unexpected sub: {row_sub}")

    await log.write(
        b"computed:\n"
        b"  original:\n"
        b"    [\n"
        + b",\n    ".join([e.__pydantic_serializer__.to_json(e) for e in original])
        + b"\n    ]\n"
        b"  merging:\n"
        b"    [\n"
        + (b",\n    ".join([e.__pydantic_serializer__.to_json(e) for e in merging]))
        + b"\n    ]\n"
    )
    query = (
        "SELECT"
        " users.sub,"
        " user_daily_reminder_settings.channel,"
        " user_daily_reminder_settings.day_of_week_mask,"
        " user_daily_reminder_settings.time_range "
        "FROM user_daily_reminder_settings, users "
        "WHERE"
        " user_daily_reminder_settings.user_id = users.id"
        " AND users.sub IN (?, ?)"
    )
    qargs = (
        original_user_sub,
        merging_user_sub,
    )
    await log.write(
        b"query:\n"
        + query.encode("utf-8")
        + b"\nqargs:\n"
        + json.dumps(qargs, indent=2).encode("utf-8")
        + b"\n"
    )
    response = await cursor.execute(query, qargs, raise_on_error=False)
    await log.write(
        b"response @ weak:\n"
        b"  results:" + json.dumps(response.results).encode("utf-8") + b"\n"
        b"  error: " + str(response.error).encode("ascii") + b"\n"
    )
    response.raise_on_error()

    original_settings_by_channel: Dict[str, RealDailyReminderChannelSettings] = dict()
    merging_settings_by_channel: Dict[str, RealDailyReminderChannelSettings] = dict()

    for row_user_sub, row_channel, row_day_of_week_mask, row_time_range in (
        response.results or []
    ):
        if row_user_sub == original_user_sub:
            original_settings_by_channel[row_channel] = (
                RealDailyReminderChannelSettings(
                    channel=row_channel,
                    days=interpret_day_of_week_mask(row_day_of_week_mask),
                    time_range=DailyReminderTimeRange.parse_db(row_time_range),
                )
            )
        elif row_user_sub == merging_user_sub:
            merging_settings_by_channel[row_channel] = RealDailyReminderChannelSettings(
                channel=row_channel,
                days=interpret_day_of_week_mask(row_day_of_week_mask),
                time_range=DailyReminderTimeRange.parse_db(row_time_range),
            )
        else:
            raise Exception(f"unexpected sub: {row_user_sub}")

    await log.write(b"computed:\n  original_settings:\n")
    for channel, settings in original_settings_by_channel.items():
        await log.write(
            b"    "
            + channel.encode("utf-8")
            + b":\n      "
            + (
                "\n      ".join(
                    settings.model_dump_json(indent=2).splitlines(keepends=False)
                )
            ).encode("utf-8")
            + b",\n"
        )
    await log.write(b"  merging_settings:\n")
    for channel, settings in merging_settings_by_channel.items():
        await log.write(
            b"    "
            + channel.encode("utf-8")
            + b":\n      "
            + (
                "\n      ".join(
                    settings.model_dump_json(indent=2).splitlines(keepends=False)
                )
            ).encode("utf-8")
            + b",\n"
        )

    original_email = get_implied_settings(
        original_settings_by_channel, "email", EMAIL_PREFERRED_CHANNELS
    )
    merging_email = get_implied_settings(
        merging_settings_by_channel, "email", EMAIL_PREFERRED_CHANNELS
    )

    await log.write(
        b"  original email implied settings:\n"
        b"    "
        + (
            "\n    ".join(
                original_email.model_dump_json(indent=2).splitlines(keepends=False)
            )
        ).encode("utf-8")
        + b"\n"
        b"  merging email implied settings:\n"
        b"    "
        + (
            "\n    ".join(
                merging_email.model_dump_json(indent=2).splitlines(keepends=False)
            )
        ).encode("utf-8")
        + b"\n"
    )
    return OauthEmailConflictInfo(
        original=original,
        merging=merging,
        original_settings=DailyReminderSettingsForConflict(
            days_of_week=original_email.days,
            start_time=original_email.start,
            end_time=original_email.end,
        ),
        merging_settings=DailyReminderSettingsForConflict(
            days_of_week=merging_email.days,
            start_time=merging_email.start,
            end_time=merging_email.end,
        ),
    )


async def get_phone_conflict_info(
    itgs: Itgs,
    *,
    original_user_sub: str,
    merging_user_sub: str,
    log: AsyncWritableBytesIO,
) -> OauthPhoneConflictInfo:
    """Assumes that there is an phone conflict between the given users and fetches
    their phone information from the database in order to form the response that
    will allow the user to resolve the conflict
    """
    query: str = (
        "SELECT"
        " users.sub,"
        " user_phone_numbers.phone_number,"
        " EXISTS (SELECT 1 FROM suppressed_phone_numbers WHERE suppressed_phone_numbers.phone_number = user_phone_numbers.phone_number) AS suppressed,"
        " user_phone_numbers.verified,"
        " user_phone_numbers.receives_notifications "
        "FROM user_phone_numbers, users "
        "WHERE"
        " user_phone_numbers.user_id = users.id"
        " AND users.sub IN (?, ?)"
    )
    qargs: Sequence[Any] = (
        original_user_sub,
        merging_user_sub,
    )
    await log.write(
        b"query:\n"
        + query.encode("utf-8")
        + b"\nqargs:\n"
        + json.dumps(qargs, indent=2).encode("utf-8")
        + b"\n"
    )
    conn = await itgs.conn()
    cursor = conn.cursor("weak")
    response = await cursor.execute(query, qargs, raise_on_error=False)
    await log.write(
        b"response @ weak:\n"
        b"  results:" + json.dumps(response.results).encode("utf-8") + b"\n"
        b"  error: " + str(response.error).encode("ascii") + b"\n"
    )
    response.raise_on_error()

    original: List[PhoneForConflict] = []
    merging: List[PhoneForConflict] = []
    for row_sub, row_phone, row_suppressed, row_verified, row_enabled in (
        response.results or []
    ):
        if row_sub == original_user_sub:
            original.append(
                PhoneForConflict(
                    phone_number=row_phone,
                    suppressed=row_suppressed,
                    verified=row_verified,
                    enabled=row_enabled,
                )
            )
        elif row_sub == merging_user_sub:
            merging.append(
                PhoneForConflict(
                    phone_number=row_phone,
                    suppressed=row_suppressed,
                    verified=row_verified,
                    enabled=row_enabled,
                )
            )
        else:
            raise Exception(f"unexpected sub: {row_sub}")

    await log.write(
        b"computed:\n"
        b"  original:\n"
        b"    [\n"
        + b",\n    ".join([e.__pydantic_serializer__.to_json(e) for e in original])
        + b"\n    ]\n"
        b"  merging:\n"
        b"    [\n"
        + (b",\n    ".join([e.__pydantic_serializer__.to_json(e) for e in merging]))
        + b"\n    ]\n"
    )
    query = (
        "SELECT"
        " users.sub,"
        " user_daily_reminder_settings.channel,"
        " user_daily_reminder_settings.day_of_week_mask,"
        " user_daily_reminder_settings.time_range "
        "FROM user_daily_reminder_settings, users "
        "WHERE"
        " user_daily_reminder_settings.user_id = users.id"
        " AND users.sub IN (?, ?)"
    )
    qargs = (
        original_user_sub,
        merging_user_sub,
    )
    await log.write(
        b"query:\n"
        + query.encode("utf-8")
        + b"\nqargs:\n"
        + json.dumps(qargs, indent=2).encode("utf-8")
        + b"\n"
    )
    response = await cursor.execute(query, qargs, raise_on_error=False)
    await log.write(
        b"response @ weak:\n"
        b"  results:" + json.dumps(response.results).encode("utf-8") + b"\n"
        b"  error: " + str(response.error).encode("ascii") + b"\n"
    )
    response.raise_on_error()

    original_settings_by_channel: Dict[str, RealDailyReminderChannelSettings] = dict()
    merging_settings_by_channel: Dict[str, RealDailyReminderChannelSettings] = dict()

    for row_user_sub, row_channel, row_day_of_week_mask, row_time_range in (
        response.results or []
    ):
        if row_user_sub == original_user_sub:
            original_settings_by_channel[row_channel] = (
                RealDailyReminderChannelSettings(
                    channel=row_channel,
                    days=interpret_day_of_week_mask(row_day_of_week_mask),
                    time_range=DailyReminderTimeRange.parse_db(row_time_range),
                )
            )
        elif row_user_sub == merging_user_sub:
            merging_settings_by_channel[row_channel] = RealDailyReminderChannelSettings(
                channel=row_channel,
                days=interpret_day_of_week_mask(row_day_of_week_mask),
                time_range=DailyReminderTimeRange.parse_db(row_time_range),
            )
        else:
            raise Exception(f"unexpected sub: {row_user_sub}")

    await log.write(b"computed:\n  original_settings:\n    ")
    for channel, settings in original_settings_by_channel.items():
        await log.write(
            b"    "
            + channel.encode("utf-8")
            + b":\n      "
            + (
                "\n      ".join(
                    settings.model_dump_json(indent=2).splitlines(keepends=False)
                )
            ).encode("utf-8")
            + b",\n"
        )
    await log.write(b"  merging_settings:\n    ")
    for channel, settings in merging_settings_by_channel.items():
        await log.write(
            b"    "
            + channel.encode("utf-8")
            + b":\n      "
            + (
                "\n      ".join(
                    settings.model_dump_json(indent=2).splitlines(keepends=False)
                )
            ).encode("utf-8")
            + b",\n"
        )

    original_sms = get_implied_settings(
        original_settings_by_channel, "sms", SMS_PREFERRED_CHANNELS
    )
    merging_sms = get_implied_settings(
        merging_settings_by_channel, "sms", SMS_PREFERRED_CHANNELS
    )

    await log.write(
        b"  original sms implied settings:\n"
        b"    "
        + (
            "\n    ".join(
                original_sms.model_dump_json(indent=2).splitlines(keepends=False)
            )
        ).encode("utf-8")
        + b"\n"
        b"  merging sms implied settings:\n"
        b"    "
        + (
            "\n    ".join(
                merging_sms.model_dump_json(indent=2).splitlines(keepends=False)
            )
        ).encode("utf-8")
        + b"\n"
    )
    return OauthPhoneConflictInfo(
        original=original,
        merging=merging,
        original_settings=DailyReminderSettingsForConflict(
            days_of_week=original_sms.days,
            start_time=original_sms.start,
            end_time=original_sms.end,
        ),
        merging_settings=DailyReminderSettingsForConflict(
            days_of_week=merging_sms.days,
            start_time=merging_sms.start,
            end_time=merging_sms.end,
        ),
    )


async def create_duplicate_identity_query(
    itgs: Itgs,
    *,
    operation_uid: str,
    original_user_sub: str,
    merging_provider: Literal[
        "Direct", "Google", "SignInWithApple", "Passkey", "Silent", "Dev"
    ],
    merging_provider_sub: str,
    log: MergeFreeformLog,
    merge_at: float,
    mal_duplicate_identity: str,
) -> Sequence[MergeQuery]:
    async def handler(ctx: MergeContext) -> None:
        affected = not not ctx.result.rows_affected
        if affected:
            await ctx.log.write(
                b"- duplicate_identity -\n"
                b"affected: True\n"
                b"interpretation: this identity was already attached to the original user\n"
                b"expectation: we didn't merge, so merging_expected is False\n"
            )
            if ctx.merging_expected:
                raise Exception(
                    "duplicate_identity affected rows, but merging_expected is True"
                )

    return [
        MergeQuery(
            query=(
                "INSERT INTO merge_account_log ("
                " uid, user_id, operation_uid, operation_order, phase, step, step_result, reason, created_at"
                ") SELECT"
                " ?, users.id, ?, ?, 'initial', 'duplicate_identity', 'yes', ?, ? "
                "FROM users "
                "WHERE"
                " users.sub = ?"
                " AND EXISTS ("
                "  SELECT 1 FROM user_identities"
                "  WHERE"
                "   user_identities.user_id = users.id"
                "   AND user_identities.provider = ?"
                "   AND user_identities.sub = ?"
                " )"
            ),
            qargs=(
                mal_duplicate_identity,
                operation_uid,
                OperationOrder.duplicate_identity.value,
                json.dumps(
                    {
                        "repo": "backend",
                        "file": __name__,
                        "context": {
                            "log": {
                                "uid": log.s3_uid,
                                "bucket": log.s3_bucket,
                                "key": log.s3_key,
                            }
                        },
                    }
                ),
                merge_at,
                original_user_sub,
                merging_provider,
                merging_provider_sub,
            ),
            handler=handler,
        )
    ]


async def create_create_identity_query(
    itgs: Itgs,
    *,
    operation_uid: str,
    original_user_sub: str,
    merging_provider: Literal[
        "Direct", "Google", "SignInWithApple", "Passkey", "Silent", "Dev"
    ],
    merging_provider_sub: str,
    merging_provider_claims: Mapping[str, Any],
    log: MergeFreeformLog,
    merge_at: float,
    mal_create_identity: str,
) -> Sequence[MergeQuery]:
    logged: Optional[bool] = None
    new_user_identity_uid = f"oseh_ui_{secrets.token_urlsafe(16)}"
    await log.out.write(
        b"- create_identity -\n"
        b"computed:\n"
        b"  new_user_identity_uid: " + new_user_identity_uid.encode("ascii") + b"\n"
    )

    async def handler(step: Literal["log", "associate"], ctx: MergeContext) -> None:
        nonlocal logged

        if step == "log":
            assert logged is None, "handler called twice for log step"
            logged = not not ctx.result.rows_affected
            if logged:
                await log.out.write(
                    b" - create_identity: 'log' - \n"
                    b"affected: True\n"
                    b"interpretation: we logged that we created a new user identity associating this provider sub with the original user\n"
                    b"expectation: we didn't merge, so merging_expected is False\n"
                )
                if ctx.merging_expected:
                    raise Exception(
                        "create_identity affected rows, but merging_expected is True"
                    )
            return

        assert step == "associate", f"unexpected step: {step}"
        assert logged is not None, "handler for associate called before log step"
        associated = not not ctx.result.rows_affected
        if associated or logged:
            await log.out.write(
                b" - create_identity: 'associate' - \n"
                b"affected: " + str(associated).encode("ascii") + b"\n"
                b"interpretation: this should always be in sync with the first query; "
                b"it refers to the query that actually inserts into the user_identities table\n"
            )
        assert associated is logged, f"{associated=} is not {logged=}"

    return [
        MergeQuery(
            query=(
                "INSERT INTO merge_account_log ("
                " uid, user_id, operation_uid, operation_order, phase, step, step_result, reason, created_at"
                ") SELECT"
                " ?, users.id, ?, ?, 'initial', 'create_identity', 'yes', ?, ? "
                "FROM users "
                "WHERE"
                " users.sub = ?"
                " AND NOT EXISTS ("
                "  SELECT 1 FROM user_identities"
                "  WHERE"
                "   user_identities.provider = ?"
                "   AND user_identities.sub = ?"
                " )"
            ),
            qargs=[
                mal_create_identity,
                operation_uid,
                OperationOrder.create_identity.value,
                json.dumps(
                    {
                        "repo": "backend",
                        "file": __name__,
                        "context": {
                            "log": {
                                "uid": log.s3_uid,
                                "bucket": log.s3_bucket,
                                "key": log.s3_key,
                            }
                        },
                    }
                ),
                merge_at,
                original_user_sub,
                merging_provider,
                merging_provider_sub,
            ],
            handler=partial(handler, "log"),
        ),
        MergeQuery(
            query=(
                "INSERT INTO user_identities ("
                " uid, user_id, provider, sub, example_claims, created_at, last_seen_at"
                ") "
                "SELECT"
                " ?, users.id, ?, ?, ?, ?, ? "
                "FROM users "
                "WHERE"
                " users.sub = ?"
                " AND EXISTS ("
                "  SELECT 1 FROM merge_account_log WHERE uid = ?"
                " )"
            ),
            qargs=(
                new_user_identity_uid,
                merging_provider,
                merging_provider_sub,
                json.dumps(merging_provider_claims),
                merge_at,
                merge_at,
                original_user_sub,
                mal_create_identity,
            ),
            handler=partial(handler, "associate"),
        ),
    ]


async def create_transfer_identity_query(
    itgs: Itgs,
    *,
    operation_uid: str,
    original_user_sub: str,
    merging_provider: Literal[
        "Direct", "Google", "SignInWithApple", "Passkey", "Silent", "Dev"
    ],
    merging_provider_sub: str,
    log: MergeFreeformLog,
    merge_at: float,
    mal_transfer_identity: str,
) -> Sequence[MergeQuery]:
    async def handler(ctx: MergeContext) -> None:
        affected = not not ctx.result.rows_affected
        if affected:
            await ctx.log.write(
                b"- transfer_identity -\n"
                b"affected: True\n"
                b"interpretation: this is either a trivial merge, in which case "
                b"merging_expected should be True, or it's a requires-input merge, "
                b"in which case merging_expected should be False.\n\n"
                b"This was decided in SQL, so we can't check that result here without "
                b"querying the log, but thats the same method used for merging_expected "
                b"so it would be redundant.\n"
            )
            return

        if ctx.merging_expected:
            await ctx.log.write(
                b"- transfer_identity -\n"
                b"affected: False\n"
                b"interpretation: this is definitely not a trivial merge, so "
                b"merging_expected should be False\n"
            )
            raise Exception(
                "transfer_identity did not affect any rows, but merging_expected is True"
            )

    return [
        MergeQuery(
            query=(
                "WITH params("
                " operation_uid,"
                " operation_order,"
                " original_user_sub,"
                " merging_provider,"
                " merging_provider_sub,"
                " merge_at,"
                " mal_transfer_identity,"
                " reason_base"
                ") AS (VALUES (?, ?, ?, ?, ?, ?, ?, ?))"
                # ---
                ", merging_user("
                " id,"
                " sub"
                ") AS MATERIALIZED ("
                "SELECT"
                " users.id,"
                " users.sub "
                "FROM user_identities, users "
                "WHERE"
                " user_identities.provider = (SELECT params.merging_provider FROM params)"
                " AND user_identities.sub = (SELECT params.merging_provider_sub FROM params)"
                " AND users.id = user_identities.user_id"
                " AND users.sub <> (SELECT params.original_user_sub FROM params)"
                ")"
                # --
                ", original_user("
                " id,"
                " sub"
                ") AS MATERIALIZED ("
                "SELECT"
                " users.id,"
                " users.sub "
                "FROM users "
                "WHERE"
                " users.sub = (SELECT params.original_user_sub FROM params)"
                ")"
                # ---
                ", original_emails("
                " email"
                ") AS MATERIALIZED ("
                "SELECT"
                " user_email_addresses.email "
                "FROM user_email_addresses "
                "WHERE"
                " user_email_addresses.user_id = (SELECT original_user.id FROM original_user)"
                " AND user_email_addresses.verified"
                " AND user_email_addresses.receives_notifications"
                " AND NOT EXISTS ("
                "  SELECT 1 FROM suppressed_emails"
                "  WHERE"
                "   suppressed_emails.email_address = user_email_addresses.email COLLATE NOCASE"
                " )"
                ")"
                # ---
                ", merging_emails("
                " email"
                ") AS MATERIALIZED ("
                "SELECT"
                " user_email_addresses.email "
                "FROM user_email_addresses "
                "WHERE"
                " user_email_addresses.user_id = (SELECT merging_user.id FROM merging_user)"
                " AND user_email_addresses.verified"
                " AND user_email_addresses.receives_notifications"
                " AND NOT EXISTS ("
                "  SELECT 1 FROM suppressed_emails"
                "  WHERE"
                "   suppressed_emails.email_address = user_email_addresses.email COLLATE NOCASE"
                " )"
                ")"
                # ---
                ", original_phone_numbers("
                " phone_number"
                ") AS MATERIALIZED ("
                "SELECT"
                " user_phone_numbers.phone_number "
                "FROM user_phone_numbers "
                "WHERE"
                " user_phone_numbers.user_id = (SELECT original_user.id FROM original_user)"
                " AND user_phone_numbers.verified"
                " AND user_phone_numbers.receives_notifications"
                " AND NOT EXISTS ("
                "  SELECT 1 FROM suppressed_phone_numbers"
                "  WHERE"
                "   suppressed_phone_numbers.phone_number = user_phone_numbers.phone_number"
                " )"
                ")"
                # ---
                ", merging_phone_numbers("
                " phone_number"
                ") AS MATERIALIZED ("
                "SELECT"
                " user_phone_numbers.phone_number "
                "FROM user_phone_numbers "
                "WHERE"
                " user_phone_numbers.user_id = (SELECT merging_user.id FROM merging_user)"
                " AND user_phone_numbers.verified"
                " AND user_phone_numbers.receives_notifications"
                " AND NOT EXISTS ("
                "  SELECT 1 FROM suppressed_phone_numbers"
                "  WHERE"
                "   suppressed_phone_numbers.phone_number = user_phone_numbers.phone_number"
                " )"
                ")"
                # ---
                ", computed_context_1("
                " email__receives_reminders__original,"
                " email__receives_reminders__merging,"
                " phone__receives_reminders__original,"
                " phone__receives_reminders__merging"
                ") AS MATERIALIZED ("
                "SELECT"
                " EXISTS ("
                "  SELECT 1 FROM user_daily_reminders"
                "  WHERE"
                "   user_daily_reminders.user_id = (SELECT original_user.id FROM original_user)"
                "   AND user_daily_reminders.channel = 'email'"
                " ),"
                " EXISTS ("
                "  SELECT 1 FROM user_daily_reminders"
                "  WHERE"
                "   user_daily_reminders.user_id = (SELECT merging_user.id FROM merging_user)"
                "   AND user_daily_reminders.channel = 'email'"
                " ),"
                " EXISTS ("
                "  SELECT 1 FROM user_daily_reminders"
                "  WHERE"
                "   user_daily_reminders.user_id = (SELECT original_user.id FROM original_user)"
                "   AND user_daily_reminders.channel = 'sms'"
                " ),"
                " EXISTS ("
                "  SELECT 1 FROM user_daily_reminders"
                "  WHERE"
                "   user_daily_reminders.user_id = (SELECT merging_user.id FROM merging_user)"
                "   AND user_daily_reminders.channel = 'sms'"
                " ) "
                "FROM params"
                ")"
                # ---
                ", computed_context_2("
                " email__conflicts,"
                " phone__conflicts"
                ") AS MATERIALIZED ("
                "SELECT"
                " ("
                "  computed_context_1.email__receives_reminders__original"
                "  AND computed_context_1.email__receives_reminders__merging"
                "  AND ("
                "   (EXISTS ("
                "    SELECT 1 FROM original_emails"
                "    WHERE NOT EXISTS ("
                "     SELECT 1 FROM merging_emails"
                "     WHERE merging_emails.email = original_emails.email COLLATE NOCASE"
                "    )"
                "   ))"
                "   OR (EXISTS ("
                "    SELECT 1 FROM merging_emails"
                "    WHERE NOT EXISTS ("
                "     SELECT 1 FROM original_emails"
                "     WHERE original_emails.email = merging_emails.email COLLATE NOCASE"
                "    )"
                "   ))"
                "  )"
                " ),"
                " ("
                "  computed_context_1.phone__receives_reminders__original"
                "  AND computed_context_1.phone__receives_reminders__merging"
                "  AND ("
                "   (EXISTS ("
                "    SELECT 1 FROM original_phone_numbers"
                "    WHERE NOT EXISTS ("
                "     SELECT 1 FROM merging_phone_numbers"
                "     WHERE merging_phone_numbers.phone_number = original_phone_numbers.phone_number"
                "    )"
                "   ))"
                "   OR (EXISTS ("
                "    SELECT 1 FROM merging_phone_numbers"
                "    WHERE NOT EXISTS ("
                "     SELECT 1 FROM original_phone_numbers"
                "     WHERE original_phone_numbers.phone_number = merging_phone_numbers.phone_number"
                "    )"
                "   ))"
                "  )"
                " ) "
                "FROM params, computed_context_1"
                ")"
                # ---
                ", step_result(value) AS MATERIALIZED ("
                "SELECT 'trivial' "
                "FROM computed_context_2, merging_user "
                "WHERE"
                " NOT computed_context_2.email__conflicts"
                " AND NOT computed_context_2.phone__conflicts "
                "UNION ALL "
                "SELECT 'requires-input' "
                "FROM computed_context_2, merging_user "
                "WHERE"
                " computed_context_2.email__conflicts"
                " OR computed_context_2.phone__conflicts "
                ") "
                # ---
                "INSERT INTO merge_account_log ("
                " uid, user_id, operation_uid, operation_order, phase, step, step_result, reason, created_at"
                ") "
                "SELECT"
                " params.mal_transfer_identity,"
                " original_user.id,"
                " params.operation_uid,"
                " params.operation_order,"
                " 'initial',"
                " 'transfer_identity',"
                " step_result.value,"
                " json_insert("
                "  params.reason_base"
                "  , '$.context.merging.user_sub', merging_user.sub"
                "  , '$.context.email.receives_reminders.original', json(iif(computed_context_1.email__receives_reminders__original, 'true', 'false'))"
                "  , '$.context.email.receives_reminders.merging', json(iif(computed_context_1.email__receives_reminders__merging, 'true', 'false'))"
                "  , '$.context.email.verified_enabled_unsuppressed.original', (SELECT json_group_array(email) FROM original_emails)"
                "  , '$.context.email.verified_enabled_unsuppressed.merging', (SELECT json_group_array(email) FROM merging_emails)"
                "  , '$.context.email.conflicts', json(iif(computed_context_2.email__conflicts, 'true', 'false'))"
                "  , '$.context.phone.receives_reminders.original', json(iif(computed_context_1.phone__receives_reminders__original, 'true', 'false'))"
                "  , '$.context.phone.receives_reminders.merging', json(iif(computed_context_1.phone__receives_reminders__merging, 'true', 'false'))"
                "  , '$.context.phone.verified_enabled_unsuppressed.original', (SELECT json_group_array(phone_number) FROM original_phone_numbers)"
                "  , '$.context.phone.verified_enabled_unsuppressed.merging', (SELECT json_group_array(phone_number) FROM merging_phone_numbers)"
                "  , '$.context.phone.conflicts', json(iif(computed_context_2.phone__conflicts, 'true', 'false'))"
                " ),"
                " params.merge_at "
                "FROM params, merging_user, computed_context_1, computed_context_2, step_result, original_user "
                "LIMIT 1"  # hint to optimizer
            ),
            qargs=(
                operation_uid,
                OperationOrder.transfer_identity.value,
                original_user_sub,
                merging_provider,
                merging_provider_sub,
                merge_at,
                mal_transfer_identity,
                json.dumps(
                    {
                        "repo": "backend",
                        "file": __name__,
                        "context": {
                            "log": {
                                "uid": log.s3_uid,
                                "bucket": log.s3_bucket,
                                "key": log.s3_key,
                            },
                            "merging": {
                                "provider": merging_provider,
                                "provider_sub": merging_provider_sub,
                            },
                        },
                    }
                ),
            ),
            handler=handler,
        )
    ]


if __name__ == "__main__":

    async def main():
        user_sub = input("user_sub: ")
        provider = input("provider: ")
        provider_sub = input("provider_sub: ")
        async with Itgs() as itgs:
            orig_user = std_auth.SuccessfulAuthResult(sub=user_sub)
            merging_user = start_merge_auth.SuccessfulAuthResult(
                original_user_sub=orig_user.sub,
                provider=cast(MergeProvider, provider),
                provider_sub=provider_sub,
                provider_claims={
                    "sub": provider_sub,
                },
                claims=None,
            )
            print(f"{orig_user=}")
            print(f"{merging_user=}")
            result = await attempt_start_merge(
                itgs, original_user=orig_user, merge=merging_user
            )
            print(f"{result=}")

    anyio.run(main)
