from dataclasses import dataclass
import gzip
import io
from pypika import Table, Query, Parameter, Order
from pypika.queries import QueryBuilder
from pypika.terms import Term
from db.utils import ParenthisizeCriterion
from typing import Any, Dict, List, Literal, Optional, Tuple, Union, cast
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
import auth as std_auth
from error_middleware import handle_warning
from lib.journals.client_keys import (
    GetJournalClientKeyResultSuccess,
    get_journal_client_key,
)
from lib.journals.data_to_client import (
    DataToClientContext,
    DataToClientInspectResult,
    bulk_prepare_data_to_client,
    data_to_client,
    inspect_data_to_client,
)
from lib.journals.journal_entry_item_data import (
    JournalEntryItemData,
    JournalEntryItemDataClient,
)
from lib.journals.master_keys import (
    GetJournalMasterKeyForEncryptionResultSuccess,
    get_journal_master_key_from_s3,
)
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from resources.filter import sort_criterion, flattened_filters
from resources.filter_bit_field_item import FilterBitFieldItemModel
from resources.filter_item import FilterItemModel
from resources.filter_item_like import FilterItemLike
from resources.sort import cleanup_sort, get_next_page_sort, reverse_sort
from resources.sort_item import SortItem, SortItemModel
from resources.filter_text_item import FilterTextItemModel
from itgs import Itgs
from visitors.lib.get_or_create_visitor import VisitorSource


class JournalEntryPayload(BaseModel):
    created_at: float = Field(
        description="When this entry was created in seconds since the epoch"
    )
    canonical_at: float = Field(
        description=(
            "The canonical time associated with this journal entry; changes over the lifetime "
            "of the journal entry, specified in seconds since the unix epoch"
        )
    )
    items: List[JournalEntryItemDataClient] = Field(
        description="The items within the entry"
    )


class JournalEntry(BaseModel):
    uid: str = Field(
        description="The primary stable external identifier for this journal entry"
    )
    encrypted_payload: str = Field(
        description="The fernet token containing the encrypted payload"
    )
    payload: Optional[JournalEntryPayload] = Field(
        None,
        description="Never set. Used for documenting the json object in the decrypted payload",
    )


@dataclass
class PendingJournalEntry:
    uid: str
    """Primary stable external identifier for this journal entry"""
    created_at: float
    """When this entry was created in seconds since the epoch"""
    canonical_at: float
    """The canonical time associated with this journal entry; changes over the lifetime of the journal entry"""
    server_items: List[JournalEntryItemData]
    """The decrypted items within this entry, not yet converted to the client representation"""


JOURNAL_ENTRY_SORT_OPTIONS = [
    SortItem[Literal["uid"], str],
    SortItem[Literal["canonical_at"], float],
]
JournalEntrySortOption = Union[
    SortItemModel[Literal["uid"], str],
    SortItemModel[Literal["canonical_at"], float],
]


class JournalEntryFilter(BaseModel):
    uid: Optional[FilterTextItemModel] = Field(
        None, description="the uid of the journal entry"
    )
    created_at: Optional[FilterItemModel[float]] = Field(
        None,
        description=(
            "the timestamp of when the journal entry was created, specified "
            "in seconds since the unix epoch"
        ),
    )
    canonical_at: Optional[FilterItemModel[float]] = Field(
        None,
        description=(
            "the canonical timestamp of the journal entry, specified in seconds "
            "since the unix epoch"
        ),
    )
    flags: Optional[FilterBitFieldItemModel] = Field(
        None,
        description=(
            "the flags associated with the journal entry, where, from least "
            "significant to most significant\n\n"
            "- bit 1: unset to prevent appearing in the My Journal tab\n"
        ),
    )


class ReadJournalEntryRequest(BaseModel):
    filters: JournalEntryFilter = Field(
        default_factory=lambda: JournalEntryFilter.model_validate({}),
        description="the filters to apply",
    )
    sort: Optional[List[JournalEntrySortOption]] = Field(
        None, description="the order to sort by"
    )
    limit: int = Field(
        25, description="the maximum number of journal entries to return", ge=1, le=250
    )


class ReadJournalEntryResponse(BaseModel):
    items: List[JournalEntry] = Field(
        description="the items matching the filters in the given sort"
    )
    next_page_sort: Optional[List[JournalEntrySortOption]] = Field(
        description=(
            "if there is a next page or an earlier page, provides the necessary "
            "sort criteria to get it"
        )
    )


router = APIRouter()

ERROR_404_TYPES = Literal["key_unavailable"]
ERROR_KEY_UNAVAILABLE_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="key_unavailable",
        message="The indicated journal client key was not found or is not acceptable for this request. Generate a new one.",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=404,
)


@router.post(
    "/search",
    response_model=ReadJournalEntryResponse,
    responses={
        **STANDARD_ERRORS_BY_CODE,
        "404": {
            "description": "The indicated journal client key was not found or is not acceptable for this request. Generate a new one.",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
    },
)
async def read_journal_entries(
    args: ReadJournalEntryRequest,
    client_key_uid: str,
    platform: VisitorSource,
    authorization: Optional[str] = Header(None),
):
    """Lists out journal entries for the authorized user.

    NOTE: We guard more metadata with the additional layer of encryption than we
    are strictly securing (since e.g., timing information can be determined by a
    passive mitm and can also be determined by the sort) to avoid accidentally
    leaking anything unnecessarily with this endpoint. Recall, again, that our
    threat model for journal entry items is passive MITM that are terminating
    TLS (e.g., corporate network or authority that forced you to install a root
    cert) and active attackers that cannot break TLS.

    When fetching a single journal entry, prefer the asynchronous websocket version
    (/sync followed by opening the websocket) which can stream the response.

    We put the client key uid to use to encrypt the entries in the query
    parameters for better consistency with other search endpoints.

    This requires standard authentication for the user whose journal entries
    are being returned.
    """
    sort = [srt.to_result() for srt in (args.sort or [])]
    sort = cleanup_sort(JOURNAL_ENTRY_SORT_OPTIONS, sort, ["uid"])
    async with Itgs() as itgs:
        std_auth_result = await std_auth.auth_any(itgs, authorization)
        if std_auth_result.result is None:
            return std_auth_result.error_response

        client_key = await get_journal_client_key(
            itgs,
            user_sub=std_auth_result.result.sub,
            journal_client_key_uid=client_key_uid,
            read_consistency="none",
        )
        if client_key.type == "not_found":
            client_key = await get_journal_client_key(
                itgs,
                user_sub=std_auth_result.result.sub,
                journal_client_key_uid=client_key_uid,
                read_consistency="weak",
            )
        if client_key.type != "success":
            await handle_warning(
                f"{__name__}:client_key:{client_key.type}",
                f"User `{std_auth_result.result.sub}` tried to read journal entries with client key `{client_key_uid}`",
            )
            return ERROR_KEY_UNAVAILABLE_RESPONSE

        if client_key.platform != platform:
            await handle_warning(
                f"{__name__}:client_key:platform",
                f"User `{std_auth_result.result.sub}` tried to read journal entries with "
                f"client key `{client_key_uid}`, which is for platform `{client_key.platform}`, "
                f"but they indicated they are on {platform}",
            )
            return ERROR_KEY_UNAVAILABLE_RESPONSE

        filters_to_apply = flattened_filters(
            dict(
                (k, cast(FilterItemLike, v.to_result()))
                for k, v in args.filters.__dict__.items()
                if v is not None
            )
        )
        items = await raw_read_journal_entries(
            itgs,
            filters_to_apply=filters_to_apply,
            sort=sort,
            limit=args.limit + 1,
            client_key=client_key,
        )
        next_page_sort: Optional[List[SortItem]] = None
        last_item: Optional[Dict[str, Any]] = None
        if len(items) > args.limit:
            items = items[: args.limit]
            last_item = item_pseudocolumns(items[-1])
        first_item: Optional[Dict[str, Any]] = None
        if items and any(s.after is not None for s in sort):
            rev_sort = reverse_sort(sort, "make_exclusive")
            rev_items = await raw_read_journal_entries(
                itgs,
                filters_to_apply=filters_to_apply,
                sort=rev_sort,
                limit=1,
                client_key=client_key,
            )
            if rev_items:
                first_item = item_pseudocolumns(items[0])

        if first_item is not None or last_item is not None:
            next_page_sort = get_next_page_sort(first_item, last_item, sort)

        for item in items:
            item.payload = None

        return Response(
            content=ReadJournalEntryResponse(
                items=items,
                next_page_sort=(
                    [s.to_model() for s in next_page_sort]
                    if next_page_sort is not None
                    else None
                ),
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )


async def raw_read_journal_entries(
    itgs: Itgs,
    /,
    *,
    filters_to_apply: List[Tuple[str, FilterItemLike]],
    sort: List[SortItem],
    limit: int,
    client_key: GetJournalClientKeyResultSuccess,
):
    """performs exactly the specified sort without pagination logic"""
    # We are going to setup the search part first to build a CTE which consists of
    # all the journal entry ids that should be in the result, then we will get the
    # joined journal entries and journal entry items from there. This allows us to
    # always get all the journal entry items associated with the journal entries
    # that we return.
    #
    # In other words, our final search query will be
    #
    # WITH q_journal_entries(id) AS (SELECT journal_entries.id FROM journal_entries WHERE ... ORDER BY ... LIMIT ...)
    # SELECT
    #  journal_entries.uid,
    #  journal_entry_items.uid
    #  # etc
    # FROM q_journal_entries
    # JOIN journal_entries ON journal_entries.id = q_journal_entries.id
    # etc
    # ORDER BY ...
    # (notice: no limit here)

    users = Table("users")
    journal_entries = Table("journal_entries")

    cte_query: QueryBuilder = (
        Query.from_(journal_entries)
        .select(journal_entries.id)
        .where(
            journal_entries.user_id
            == ParenthisizeCriterion(
                Query.from_(users).select(users.id).where(users.sub == Parameter("?"))
            )
        )
    )
    cte_qargs: List[Any] = [client_key.user_sub]

    def pseudocolumn(key: str) -> Term:
        if key in ("uid", "flags", "created_at", "canonical_at"):
            return journal_entries.field(key)
        raise ValueError(f"unknown key {key}")

    for key, filter in filters_to_apply:
        cte_query = cte_query.where(filter.applied_to(pseudocolumn(key), cte_qargs))

    cte_query = cte_query.where(sort_criterion(sort, pseudocolumn, cte_qargs))

    for srt in sort:
        cte_query = cte_query.orderby(pseudocolumn(srt.key), order=srt.order)

    cte_query = cte_query.limit(Parameter("?"))
    cte_qargs.append(limit)

    q_journal_entries = Table("q_journal_entries")
    journal_entry_items = Table("journal_entry_items")
    user_journal_master_keys = Table("user_journal_master_keys")
    s3_files = Table("s3_files")

    select_query: QueryBuilder = (
        Query.from_(q_journal_entries)
        .select(
            journal_entries.uid,
            journal_entries.created_at,
            journal_entries.canonical_at,
            journal_entry_items.entry_counter,
            user_journal_master_keys.uid,
            s3_files.key,
            journal_entry_items.master_encrypted_data,
        )
        .join(journal_entries)
        .on(journal_entries.id == q_journal_entries.id)
        .left_join(journal_entry_items)
        .on(journal_entry_items.journal_entry_id == q_journal_entries.id)
        .left_join(user_journal_master_keys)
        .on(
            (
                user_journal_master_keys.id
                == journal_entry_items.user_journal_master_key_id
            )
            & (
                user_journal_master_keys.user_id
                == ParenthisizeCriterion(
                    Query.from_(users)
                    .select(users.id)
                    .where(users.sub == Parameter("?"))
                )
            )
        )
        .left_join(s3_files)
        .on(s3_files.id == user_journal_master_keys.s3_file_id)
    )
    select_qargs: List[Any] = [client_key.user_sub]

    for srt in sort:
        select_query = select_query.orderby(pseudocolumn(srt.key), order=srt.order)

    select_query.orderby(journal_entry_items.entry_counter, order=Order.asc)

    query = io.StringIO()
    qargs = []

    query.write("WITH q_journal_entries(id) AS (")
    query.write(cte_query.get_sql())
    qargs.extend(cte_qargs)
    query.write(") ")
    query.write(select_query.get_sql())
    qargs.extend(select_qargs)

    conn = await itgs.conn()
    cursor = conn.cursor("none")
    response = await cursor.execute(query.getvalue(), qargs)

    pending_items: List[PendingJournalEntry] = []
    master_keys_by_uid: Dict[str, GetJournalMasterKeyForEncryptionResultSuccess] = (
        dict()
    )

    current_item: Optional[PendingJournalEntry] = None

    for row in response.results or []:
        row_journal_entry_uid = cast(str, row[0])
        row_journal_entry_created_at = cast(float, row[1])
        row_journal_entry_canonical_at = cast(float, row[2])
        row_journal_entry_item_counter = cast(Optional[int], row[3])
        row_user_journal_master_key_uid = cast(Optional[str], row[4])
        row_s3_file_key = cast(Optional[str], row[5])
        row_journal_entry_item_master_encrypted_data = cast(Optional[str], row[6])

        if current_item is not None and current_item.uid != row_journal_entry_uid:
            pending_items.append(current_item)
            current_item = None

        if current_item is None:
            current_item = PendingJournalEntry(
                uid=row_journal_entry_uid,
                created_at=row_journal_entry_created_at,
                canonical_at=row_journal_entry_canonical_at,
                server_items=[],
            )

        if row_journal_entry_item_counter is not None:
            assert row_user_journal_master_key_uid is not None, row
            assert row_s3_file_key is not None, row
            assert row_journal_entry_item_master_encrypted_data is not None, row

            row_master_key = master_keys_by_uid.get(row_user_journal_master_key_uid)
            if row_master_key is None:
                _row_master_key = await get_journal_master_key_from_s3(
                    itgs,
                    user_journal_master_key_uid=row_user_journal_master_key_uid,
                    user_sub=client_key.user_sub,
                    s3_key=row_s3_file_key,
                )
                if _row_master_key.type != "success":
                    await handle_warning(
                        f"{__name__}:master_key:{_row_master_key.type}",
                        f"While decryption journal entry `{row_journal_entry_uid}`, entry counter `{row_journal_entry_item_counter}` for user `{client_key.user_sub}`, the master key `{row_user_journal_master_key_uid}` was unavailable",
                    )
                    raise ValueError("master key unavailable")
                master_keys_by_uid[row_user_journal_master_key_uid] = _row_master_key
                row_master_key = _row_master_key

            try:
                decrypted_data = JournalEntryItemData.model_validate_json(
                    gzip.decompress(
                        row_master_key.journal_master_key.decrypt(
                            row_journal_entry_item_master_encrypted_data, ttl=None
                        )
                    )
                )
                current_item.server_items.append(decrypted_data)
            except Exception as e:
                await handle_warning(
                    f"{__name__}:failed_decrypt",
                    f"failed to decrypt journal entry `{row_journal_entry_uid}`, entry counter `{row_journal_entry_item_counter}` for user `{client_key.user_sub}`",
                    exc=e,
                )

    if current_item is not None:
        pending_items.append(current_item)
        current_item = None

    inspect_result = DataToClientInspectResult(
        pro=False, journeys=set(), voice_notes=set()
    )
    for entry in pending_items:
        for entry_item in entry.server_items:
            inspect_data_to_client(entry_item, out=inspect_result)

    ctx = DataToClientContext(
        user_sub=client_key.user_sub,
        has_pro=None,
        memory_cached_journeys=dict(),
        memory_cached_voice_notes=dict(),
    )
    await bulk_prepare_data_to_client(itgs, ctx=ctx, inspect=inspect_result)

    result: List[JournalEntry] = []
    for item in pending_items:
        payload = JournalEntryPayload(
            created_at=item.created_at,
            canonical_at=item.canonical_at,
            items=[
                await data_to_client(
                    itgs,
                    ctx=ctx,
                    item=item_item,
                )
                for item_item in item.server_items
            ],
        )
        result.append(
            JournalEntry(
                uid=item.uid,
                encrypted_payload=client_key.journal_client_key.encrypt(
                    JournalEntryPayload.__pydantic_serializer__.to_json(payload)
                ).decode("ascii"),
                payload=payload,
            )
        )
    return result


def item_pseudocolumns(item: JournalEntry) -> dict:
    """returns the dictified item such that the keys in the return dict match
    the keys of the sort options"""
    assert item.payload is not None
    return {
        "uid": item.uid,
        "created_at": item.payload.created_at,
        "canonical_at": item.payload.canonical_at,
    }
