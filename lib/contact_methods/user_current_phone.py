"""Convenience module for getting a users current phone number. This
is only relevant when referring to an authorized request, and provides
the most relevant context-sensitive phone for the user authorized in
the given way.

This is generally appropriate for prefilling forms where only a single
phone number can be provided, such as a stripe payment form.
"""

from itgs import Itgs
from auth import AuthResult
from typing import Literal, Optional, Tuple, Union
from pypika import Query, Parameter, Table
from pypika.terms import ExistsCriterion
from enum import Enum
from lib.contact_methods.user_primary_phone import primary_phone_join_clause


class _NotSetEnum(Enum):
    NotSet = 0


NOT_SET = _NotSetEnum.NotSet


async def get_user_current_phone(
    itgs: Itgs,
    auth_result: AuthResult,
    *,
    default: Union[str, None, Literal[_NotSetEnum.NotSet]] = NOT_SET
) -> Optional[str]:
    """Gets the users current phone number in E.164 format. It's possible that
    the authorization method doesn't provide a phone number and there are none
    associated with the user. In that case, if no default is specified then an
    error is raised. Otherwise, the default is returned.

    Args:
        itgs (Itgs): the integrations to (re)use
        auth_result (AuthResult): the authorization result to use
        default (Optional[str], optional): the default phone number to use if
            none is found. Defaults to NotSet, meaning a ValueError will be raised
    """
    if auth_result.result is None:
        raise ValueError("auth_result must be successful")

    if auth_result.result.claims is None:
        return await _fallback_to_primary(itgs, auth_result.result.sub, default=default)

    phone = auth_result.result.claims.get("phone_number")
    if phone is None:
        return await _fallback_to_primary(itgs, auth_result.result.sub, default=default)

    return phone


async def _fallback_to_primary(
    itgs: Itgs, sub: str, default: Union[str, None, Literal[_NotSetEnum.NotSet]]
):
    conn = await itgs.conn()
    cursor = conn.cursor("none")

    users = Table("users")
    user_phone_numbers = Table("user_phone_numbers")
    response = await cursor.execute(
        Query.from_(user_phone_numbers)
        .select(user_phone_numbers.phone_number)
        .where(
            ExistsCriterion(
                Query.from_(users)
                .select(1)
                .where(users.sub == Parameter("?"))
                .where(primary_phone_join_clause())
            )
        )
        .get_sql(),
        (sub,),
    )

    if not response.results:
        if default is NOT_SET:
            raise ValueError("No phone number found for user")
        return default

    return response.results[0][0]


def select_best_current_phone(
    provider_phone: Optional[str],
    provider_phone_verified: bool,
    primary_phone: Optional[str],
    primary_phone_verified: bool,
) -> Tuple[Optional[str], bool]:
    """Selects the best current phone number to use for the login JWT
    given the option from the provider and the option in our database

    Args:
        provider_phone (Optional[str]): the phone number from the provider
        provider_phone_verified (bool): whether the provider phone number is verified
        primary_phone (Optional[str]): the phone number from our database
        primary_phone_verified (bool): whether the primary phone number is verified

    Returns:
        (str or None, bool): The best phone number and if it's verified
    """
    if provider_phone is None and primary_phone is None:
        return None, False

    if provider_phone is None:
        return primary_phone, primary_phone_verified

    if primary_phone is None:
        return provider_phone, provider_phone_verified

    if provider_phone_verified and not primary_phone_verified:
        return provider_phone, True

    if primary_phone_verified and not provider_phone_verified:
        return primary_phone, True

    return provider_phone, True
