"""Convenience module for getting a users current email address. This
is only relevant when referring to an authorized request, and provides
the most relevant context-sensitive email for the user authorized in
the given way.

This is generally appropriate for prefilling forms where only a single
email address can be provided, such as a stripe payment form.
"""

from itgs import Itgs
from auth import AuthResult
from typing import Literal, Optional, Tuple, Union, cast
from pypika import Query, Parameter, Table
from pypika.terms import ExistsCriterion
from enum import Enum
from lib.contact_methods.user_primary_email import primary_email_join_clause


class _NotSetEnum(Enum):
    NotSet = 0


NotSet = _NotSetEnum.NotSet


async def get_user_current_email(
    itgs: Itgs,
    auth_result: AuthResult,
    *,
    default: Optional[Union[str, Literal[_NotSetEnum.NotSet]]] = NotSet
) -> Optional[str]:
    """Gets the users current email address. It's possible, though unlikely, that
    the authorization method doesn't provide an email address and there are none
    associated with the user. In that case, if no default is specified then an
    error is raised. Otherwise, the default is returned.

    Args:
        itgs (Itgs): the integrations to (re)use
        auth_result (AuthResult): the authorization result to use
        default (Optional[str], optional): the default email address to use if
            none is found. Defaults to NotSet, meaning a ValueError will be raised
    """
    if auth_result.result is None:
        raise ValueError("auth_result must be successful")

    if auth_result.result.claims is None:
        return cast(
            Union[str, None],
            await _fallback_to_primary(itgs, auth_result.result.sub, default=default),
        )

    email = auth_result.result.claims.get("email")
    if email in (None, "anonymous@example.com"):
        return cast(
            Union[str, None],
            await _fallback_to_primary(itgs, auth_result.result.sub, default=default),
        )

    return email


async def _fallback_to_primary(
    itgs: Itgs, sub: str, default: Union[str, None, Literal[_NotSetEnum.NotSet]]
):
    conn = await itgs.conn()
    cursor = conn.cursor("none")

    users = Table("users")
    user_email_addresses = Table("user_email_addresses")
    response = await cursor.execute(
        Query.from_(user_email_addresses)
        .select(user_email_addresses.email)
        .where(
            ExistsCriterion(
                Query.from_(users)
                .select(1)
                .where(users.sub == Parameter("?"))
                .where(primary_email_join_clause())
            )
        )
        .get_sql(),
        (sub,),
    )

    if not response.results:
        if default is NotSet:
            raise ValueError("No email address found for user")
        return default

    return response.results[0][0]


def is_relay_email(email: str) -> bool:
    """Determines if the given email address is a known relay"""
    return email.endswith("@privaterelay.appleid.com")


def select_best_current_email(
    provider_email: Optional[str],
    provider_email_verified_claim: bool,
    primary_email: Optional[str],
    primary_email_verified: bool,
) -> Tuple[Optional[str], bool]:
    """Selects the email address to use for the id token given the two options
    of the one from their provider and their primary email address in our database.

    Args:
        provider_email (str): the email address from the provider
        provider_email_verified_claim (bool): whether the provider email address
            has been verified
        primary_email (str): the primary email address from our database
        primary_email_verified (bool): whether the primary email address has been
            verified

    Returns:
        (str or None, bool): the email and if its verified
    """
    if provider_email is None and primary_email is None:
        return None, False

    if provider_email is None:
        return primary_email, primary_email_verified

    if primary_email is None:
        return provider_email, provider_email_verified_claim

    provider_is_relay = is_relay_email(provider_email)
    primary_is_relay = is_relay_email(primary_email)
    if provider_is_relay and not primary_is_relay:
        return primary_email, primary_email_verified
    if primary_is_relay and not provider_is_relay:
        return provider_email, provider_email_verified_claim

    if provider_email_verified_claim and not primary_email_verified:
        return provider_email, provider_email_verified_claim
    if primary_email_verified and not provider_email_verified_claim:
        return primary_email, primary_email_verified

    return provider_email, provider_email_verified_claim
