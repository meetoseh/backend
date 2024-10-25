import json
import os
import secrets
import socket
import time
import traceback
from typing import Any, List, Literal, Optional, Sequence, cast

from error_middleware import handle_error
from itgs import Itgs
import auth as std_auth
from lib.redis_stats_preparer import RedisStatsPreparer
import oauth.lib.merging.confirm_merge_auth as confirm_merge_auth
from oauth.lib.merging.core import create_merging_queries
from oauth.lib.merging.log import MergeFreeformLog, merge_freeform_log
from oauth.lib.merging.operation_order import OperationOrder
from oauth.lib.merging.query import MergeContext, MergeQuery
from users.lib.entitlements import get_entitlement


async def attempt_confirm_merge(
    itgs: Itgs,
    /,
    *,
    original_user: std_auth.SuccessfulAuthResult,
    merge: confirm_merge_auth.SuccessfulAuthResult,
    email_hint: Optional[str],
    phone_hint: Optional[str],
) -> bool:
    """Completes the merge of the user on the oseh platform identified by
    the provider and provider sub in the merge auth result into the user
    on the oseh platform identified by the Oseh JWT in the original auth
    using an email and/or phone number hint to reconcile conflicts.

    Returns True if the merge was successful, False if the merge was
    unsuccessful because something changed between the user receiving
    the confirm merge prompt and the user submitting the confirm merge
    prompt, and raises an exception if the merge was unsuccessful for
    any other reason.

    Args:
        itgs (Itgs): the integrations to (re)use
        original_user (std_auth.SuccessfulAuthResult): the original user
            to merge into
        merge (confirm_merge_auth.SuccessfulAuthResult): the user to
            merge into the original user
        email_hint (str, None): the email hint; if provided, all email
            addresses on the original user and merging user which do not
            match this hint (case insensitive) are disabled during the
            merge.
        phone_hint (str, None): the phone hint; if provided, all phone
            numbers on the original user and merging user which do not
            match this hint (case insensitive) are disabled during the
            merge.
    """
    assert email_hint is not None or phone_hint is not None
    assert (email_hint is not None) is merge.conflicts.email
    assert (phone_hint is not None) is merge.conflicts.phone
    assert original_user.sub == merge.original_user_sub
    assert merge.original_user_sub != merge.merging_user_sub

    merge_at = time.time()
    operation_uid = f"oseh_mal_o_{secrets.token_urlsafe(16)}"
    mal_confirm = f"oseh_mal_{secrets.token_urlsafe(16)}"
    merge_provider = cast(
        Literal["Direct", "Google", "SignInWithApple", "Dev", "Passkey", "Silent"],
        merge.provider,
    )

    async with merge_freeform_log(itgs, operation_uid=operation_uid) as log:
        await log.out.write(
            b"---LOG START---\n"
            b"Action: confirm merge\n"
            b"Environment:\n"
            b"  " + os.environ["ENVIRONMENT"].encode("utf-8") + b"\n"
            b"  socket.gethostname() = " + socket.gethostname().encode("utf-8") + b"\n"
            b"\n\n"
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
            b"    original_user_sub: " + merge.original_user_sub.encode("utf-8") + b"\n"
            b"    merging_user_sub: " + merge.merging_user_sub.encode("utf-8") + b"\n"
            b"    conflicts:\n"
            b"      email: " + str(merge.conflicts.email).encode("utf-8") + b"\n"
            b"      phone: " + str(merge.conflicts.phone).encode("utf-8") + b"\n"
            b"    claims:\n    "
            + "\n    ".join(
                json.dumps(merge.claims, indent=2).splitlines(keepends=False)
            ).encode("utf-8")
            + b"\n"
            b"  email_hint: " + str(email_hint).encode("utf-8") + b"\n"
            b"  phone_hint: " + str(phone_hint).encode("utf-8") + b"\n"
            b"\n\n"
            b"Top-level computed values:\n"
            b"  merge_at=" + str(merge_at).encode("ascii") + b"\n"
            b"  operation_uid=" + operation_uid.encode("ascii") + b"\n"
            b"  mal_confirm=" + mal_confirm.encode("ascii") + b"\n"
            b"\n\n"
            b"---Initializing Queries---\n"
        )
        queries: List[MergeQuery] = [
            *await create_confirm_query(
                itgs,
                operation_uid=operation_uid,
                original_user_sub=original_user.sub,
                merging_provider=merge_provider,
                merging_provider_sub=merge.provider_sub,
                merging_user_sub=merge.merging_user_sub,
                email_hint=email_hint,
                phone_hint=phone_hint,
                log=log,
                merge_at=merge_at,
                mal_confirm=mal_confirm,
            ),
            *await create_merging_queries(
                itgs,
                confirm_log_uid=mal_confirm,
                confirm_required_step_result="success",
                operation_uid=operation_uid,
                original_user_sub=original_user.sub,
                merging_provider=merge_provider,
                merging_provider_sub=merge.provider_sub,
                log=log.out,
                merge_at=merge_at,
                email_hint=email_hint,
                phone_hint=phone_hint,
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
            result = await cursor2.executemany2(
                [q.query for q in queries],
                [q.qargs for q in queries],
                raise_on_error=False,
            )

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

        merge_result: Optional[bool] = None
        merge_result_error: Optional[Exception] = None

        try:
            merge_result = await get_merge_result(
                itgs,
                mal_confirm=mal_confirm,
                log=log,
            )
            await log.out.write(
                b"merge_result: " + str(merge_result).encode("ascii") + b"\n"
            )
        except Exception as e:
            await handle_error(
                e,
                extra_info=f"{operation_uid=} for {merge.merging_user_sub=} into {merge.original_user_sub=}",
            )
            await log.out.write(
                b"merge_result: error\n"
                + traceback.format_exc().encode("utf-8")
                + b"\n"
            )
            merge_result_error = e

        merging_expected = merge_result is True
        await log.out.write(
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

        if merge_result_error is not None:
            await log.out.write(b"Raising merge result error\n")
            raise merge_result_error

        assert merge_result is not None
        await log.out.write(b"Returning merge result\n")
        return merge_result


async def create_confirm_query(
    itgs: Itgs,
    /,
    *,
    operation_uid: str,
    original_user_sub: str,
    merging_user_sub: str,
    merging_provider: Literal[
        "Direct", "Google", "SignInWithApple", "Passkey", "Silent", "Dev"
    ],
    merging_provider_sub: str,
    log: MergeFreeformLog,
    merge_at: float,
    mal_confirm: str,
    email_hint: Optional[str],
    phone_hint: Optional[str],
) -> Sequence[MergeQuery]:
    """Creates the queries necessary to write the confirm entry in the
    merge account log
    """

    async def handler(ctx: MergeContext) -> None:
        affected = not not ctx.result.rows_affected
        if not affected:
            await ctx.log.write(
                b"- confirm -\n"
                b"affected: False\n"
                b"interpretation: the original user was deleted\n"
            )
            assert ctx.merging_expected is False
            return

        await ctx.log.write(
            b"- confirm -\n"
            b"affected: True\n"
            b"interpretation: we were able to decide if we should proceed with the merge; "
            b"we would have to check the step_result to determine if the merge\n"
        )

    return [
        MergeQuery(
            query=(
                "WITH params("
                " mal_confirm, operation_uid, operation_order, original_user_sub,"
                " merging_user_sub, merging_provider, merging_provider_sub,"
                " merge_at, email_hint, phone_hint"
                ") AS ("
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                "), merging_user_based_on_identity(id, sub) AS ("
                "SELECT users.id, users.sub FROM user_identities, users, params "
                "WHERE"
                " users.id = user_identities.user_id"
                " AND user_identities.provider = params.merging_provider"
                " AND user_identities.sub = params.merging_provider_sub"
                "), original_user(id, has_email_hint, has_phone_hint) AS ("
                "SELECT"
                " users.id,"
                " (params.email_hint IS NOT NULL) AND EXISTS ("
                "  SELECT 1 FROM user_email_addresses AS uea"
                "  WHERE uea.user_id = users.id AND uea.email = params.email_hint COLLATE NOCASE"
                " ),"
                " (params.phone_hint IS NOT NULL) AND EXISTS ("
                "  SELECT 1 FROM user_phone_numbers AS upn"
                "  WHERE upn.user_id = users.id AND upn.phone_number = params.phone_hint"
                " ) "
                "FROM users, params "
                "WHERE"
                " users.sub = params.original_user_sub"
                "), merging_user(id, has_email_hint, has_phone_hint) AS ("
                "SELECT"
                " merging_user_based_on_identity.id,"
                " (params.email_hint IS NOT NULL) AND EXISTS ("
                "  SELECT 1 FROM user_email_addresses AS uea"
                "  WHERE uea.user_id = merging_user_based_on_identity.id AND uea.email = params.email_hint COLLATE NOCASE"
                " ),"
                " (params.phone_hint IS NOT NULL) AND EXISTS ("
                "  SELECT 1 FROM user_phone_numbers AS upn"
                "  WHERE upn.user_id = merging_user_based_on_identity.id AND upn.phone_number = params.phone_hint"
                " ) "
                "FROM merging_user_based_on_identity, params "
                "WHERE"
                " merging_user_based_on_identity.sub = params.merging_user_sub"
                "), step_result(value) AS ("
                "SELECT"
                " CASE WHEN ("
                "  EXISTS (SELECT 1 FROM original_user)"
                "  AND EXISTS (SELECT 1 FROM merging_user)"
                "  AND ("
                "   params.email_hint IS NULL"
                "   OR EXISTS (SELECT 1 FROM original_user WHERE original_user.has_email_hint)"
                "   OR EXISTS (SELECT 1 FROM merging_user WHERE merging_user.has_email_hint)"
                "  )"
                "  AND ("
                "   params.phone_hint IS NULL"
                "   OR EXISTS (SELECT 1 FROM original_user WHERE original_user.has_phone_hint)"
                "   OR EXISTS (SELECT 1 FROM merging_user WHERE merging_user.has_phone_hint)"
                "  )"
                " ) THEN 'success' ELSE 'failure' END "
                "FROM params"
                ") INSERT INTO merge_account_log ("
                " uid, user_id, operation_uid, operation_order, phase, step, step_result, reason, created_at"
                ") SELECT"
                " params.mal_confirm, original_user.id, params.operation_uid, params.operation_order, 'confirm', 'confirm', "
                " step_result.value,"
                " json_insert(?"
                "  , '$.context.merging.user_sub', (SELECT sub FROM merging_user_based_on_identity)"
                "  , '$.context.email.hint_is_original', json(iif(EXISTS (SELECT 1 FROM original_user WHERE original_user.has_email_hint), 'true', 'false'))"
                "  , '$.context.email.hint_is_merging', json(iif(EXISTS (SELECT 1 FROM merging_user WHERE merging_user.has_email_hint), 'true', 'false'))"
                "  , '$.context.phone.hint_is_original', json(iif(EXISTS (SELECT 1 FROM original_user WHERE original_user.has_phone_hint), 'true', 'false'))"
                "  , '$.context.phone.hint_is_merging', json(iif(EXISTS (SELECT 1 FROM merging_user WHERE merging_user.has_phone_hint), 'true', 'false'))"
                " ), params.merge_at "
                "FROM params, step_result, original_user"
            ),
            qargs=[
                mal_confirm,
                operation_uid,
                OperationOrder.confirm.value,
                original_user_sub,
                merging_user_sub,
                merging_provider,
                merging_provider_sub,
                merge_at,
                email_hint,
                phone_hint,
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
                                "expected_user_sub": merging_user_sub,
                            },
                            "email": {
                                "hint": email_hint,
                            },
                            "phone": {
                                "hint": phone_hint,
                            },
                        },
                    }
                ),
            ],
            handler=handler,
        )
    ]


async def get_merge_result(
    itgs: Itgs,
    /,
    *,
    mal_confirm: str,
    log: MergeFreeformLog,
) -> bool:
    conn = await itgs.conn()
    cursor = conn.cursor("strong")

    query: str = "SELECT step_result, reason FROM merge_account_log WHERE uid = ?"
    qargs: Sequence[Any] = (mal_confirm,)
    await log.out.write(
        b"query:\n"
        + query.encode("utf-8")
        + b"\nqargs:\n"
        + json.dumps(qargs, indent=2).encode("utf-8")
        + b"\n"
    )
    response = await cursor.execute(query, qargs)
    await log.out.write(
        b"response @ strong:\n"
        b"  results:" + json.dumps(response.results).encode("utf-8") + b"\n"
        b"  error: " + str(response.error).encode("ascii") + b"\n"
    )
    response.raise_on_error()
    if not response.results:
        await log.out.write(
            b"there was no confirm entry written to the merge account log,\n"
            b"which means that the original user was deleted."
        )
        return False

    assert response.results[0][0] in ("success", "failure"), response
    result = cast(Literal["success", "failure"], response.results[0][0])
    reason = cast(str, response.results[0][1])
    await log.out.write(b"result: " + str(result).encode("ascii") + b"\n")

    parsed_reason = json.loads(reason)
    await log.out.write(
        b"parsed_reason:\n"
        + json.dumps(parsed_reason, indent=2).encode("utf-8")
        + b"\n"
    )

    if result != "success":
        await log.out.write(
            b"the merge entry was written but failed, raising an error\n"
        )
        raise Exception(f"the merge failed: {reason}")

    return True
