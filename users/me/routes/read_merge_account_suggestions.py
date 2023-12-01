from typing import FrozenSet, List, Annotated, Literal, Optional, cast
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from error_middleware import handle_warning
from models import STANDARD_ERRORS_BY_CODE
import auth
from itgs import Itgs
from loguru import logger


router = APIRouter()


MergeProvider = Literal["Google", "SignInWithApple", "Direct", "Dev"]
merge_providers: FrozenSet[MergeProvider] = frozenset(
    (
        "Google",
        "SignInWithApple",
        "Direct",
        "Dev",
    )
)


class MergeAccountSuggestionsResponse(BaseModel):
    channels: List[MergeProvider] = Field(
        description=(
            "Contains a list of providers that the user should try logging in "
            "with using the merge flow, as it's possible they have another "
            "user on the Oseh platform that can be identified using this provider. "
            "The user is free to ignore this request or try other providers"
        ),
        min_length=1,
    )


@router.get(
    "/merge_account_suggestions",
    response_model=MergeAccountSuggestionsResponse,
    responses={
        "204": {"description": "We have no suggested providers for the user"},
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def read_merge_account_suggestions(
    authorization: Annotated[Optional[str], Header()] = None
):
    """Should be called after the user logs in or when they change their
    name, though not too frequently. This heuristically determines if the
    authorized user might have inadvertently created multiple users on the Oseh
    platform. For example, if example@gmail.com creates an account via Sign in
    with Oseh, then the same email creates an account via Sign in with Google.
    If the authorized user is the former account, this would suggest they try
    using the merge flow with Sign in with Google. If they do login with the
    same identity, confirming they are the real owner of both users, they will
    get merged together and the user can then login using either method in the
    future to get to the same user on the Oseh platform.

    Requires standard authorization for the logged in user
    """
    async with Itgs() as itgs:
        auth_id_result = await auth.auth_id(itgs, authorization)
        if auth_id_result.result is None:
            auth_any_result = await auth.auth_any(itgs, authorization)
            if auth_any_result.success:
                logger.warning(
                    "Ignoring merge account suggestions request for non id token user"
                )
                return Response(status_code=204)
            return auth_id_result.error_response

        logger.info(
            f"Checking for merge suggestions for user {auth_id_result.result.sub} ({auth_id_result.result.claims})"
        )

        conn = await itgs.conn()
        cursor = conn.cursor("none")

        # PERF: Spent some time fiddling with this query to get it to be fast.
        # Current query plan:
        #
        # --CO-ROUTINE mergable_providers
        #   |--MULTI-INDEX OR
        #      |--INDEX 1
        #         |--LIST SUBQUERY 4
        #            |--SEARCH original USING COVERING INDEX sqlite_autoindex_users_1 (sub=?)
        #            |--SEARCH uea_original USING INDEX user_email_addresses_user_idx (user_id=?)
        #            |--SEARCH uea_merging USING INDEX user_email_addresses_email_idx (email=?)
        #         |--SEARCH user_identities USING INDEX user_identities_user_id_idx (user_id=?)
        #      |--INDEX 2
        #         |--LIST SUBQUERY 5
        #            |--SEARCH original USING INDEX sqlite_autoindex_users_1 (sub=?)
        #            |--SEARCH merging USING INDEX users_trimmed_name_insensitive_idx (<expr>=?)
        #         |--SEARCH user_identities USING INDEX user_identities_user_id_idx (user_id=?)
        #   |--SCALAR SUBQUERY 3
        #      |--SEARCH users USING COVERING INDEX sqlite_autoindex_users_1 (sub=?)
        #   |--USE TEMP B-TREE FOR DISTINCT
        # --SCAN mergable_providers
        # --CORRELATED SCALAR SUBQUERY 7
        #   |--SEARCH original USING COVERING INDEX sqlite_autoindex_users_1 (sub=?)
        #   |--SEARCH ui USING INDEX user_identities_user_id_idx (user_id=?)
        #
        response = await cursor.execute(
            "WITH mergable_users_by_email(id) AS ("
            "SELECT"
            " uea_merging.user_id "
            "FROM user_email_addresses AS uea_merging, users AS original, user_email_addresses AS uea_original "
            "WHERE"
            " original.sub = ?"
            " AND uea_original.user_id = original.id"
            " AND uea_original.email <> 'anonymous@example.com' COLLATE NOCASE"
            " AND uea_merging.email = uea_original.email COLLATE NOCASE"
            "), mergable_users_by_name(id) AS ("
            "SELECT"
            " merging.id "
            "FROM users AS merging, users AS original "
            "WHERE"
            " original.sub = ?"
            " AND original.given_name <> 'Anonymous'"
            " AND merging.id <> original.id"
            " AND merging.given_name IS NOT NULL"
            " AND merging.family_name IS NOT NULL"
            " AND original.given_name IS NOT NULL"
            " AND original.family_name IS NOT NULL"
            " AND TRIM(merging.given_name || ' ' || merging.family_name) = TRIM(original.given_name || ' ' || original.family_name) COLLATE NOCASE"
            "), mergable_providers(provider) AS ("
            "SELECT DISTINCT provider FROM user_identities "
            "WHERE"
            " user_id <> (SELECT id FROM users WHERE sub = ?)"
            " AND (user_id IN mergable_users_by_email OR user_id IN mergable_users_by_name)"
            ") "
            "SELECT provider FROM mergable_providers "
            "WHERE"
            " NOT EXISTS ("
            "  SELECT 1 FROM user_identities AS ui, users AS original"
            "  WHERE"
            "   original.sub = ?"
            "   AND ui.user_id = original.id"
            "   AND ui.provider = mergable_providers.provider"
            " )",
            [
                auth_id_result.result.sub,
                auth_id_result.result.sub,
                auth_id_result.result.sub,
                auth_id_result.result.sub,
            ],
        )
        if not response.results:
            logger.info(
                f"No merge suggestions for {auth_id_result.result.sub} ({auth_id_result.result.claims})"
            )
            return Response(status_code=204)

        providers: List[MergeProvider] = []
        for row in response.results:
            if row[0] not in merge_providers:
                await handle_warning(
                    f"{__name__}:unknown_provider",
                    f"Ignoring unknown provider `{row[0]}` as merge suggestion for user {auth_id_result.result.sub}",
                )
            providers.append(cast(MergeProvider, row[0]))

        logger.info(
            f"Providing merge suggestions for {auth_id_result.result.sub}: {providers=}"
        )
        return Response(
            content=MergeAccountSuggestionsResponse(
                channels=providers
            ).model_dump_json(),
            status_code=200,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
