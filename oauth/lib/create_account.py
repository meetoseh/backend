"""This module is meant to be invoked directly to create a new
direct account
"""
import hashlib
import secrets
from itgs import Itgs
from argparse import ArgumentParser
import asyncio
import base64
from oauth.siwo.lib.key_derivation import create_new_key_derivation_method
import time
import getpass
from loguru import logger


def main():
    parser = ArgumentParser()
    parser.add_argument("--email", required=True)
    parser.add_argument("--email-verified", action="store_true")
    parser.add_argument("--echo-password", action="store_true")
    args = parser.parse_args()

    if args.echo_password:
        password = input("**WARNING: Password will be echoed**\nPassword: ")
    else:
        password = getpass.getpass("**Password will be hidden**\nPassword: ")

    asyncio.run(
        create_account(
            email=args.email,
            email_verified=args.email_verified,
            password=password,
        )
    )


async def create_account(*, email: str, email_verified: bool, password: str):
    """Creates a new Sign in with Oseh identity with the given email and password,
    if one does not already exist.

    Args:
        email (str): The email to create the account with
        email_verified (bool): Whether the email is verified
        password (str): The password to create the account with
    """
    uid = f"oseh_da_{secrets.token_urlsafe(64)}"
    key_derivation_method = create_new_key_derivation_method()
    assert key_derivation_method.name == "pbkdf2_hmac"
    derived_password = hashlib.pbkdf2_hmac(
        key_derivation_method.hash_name,
        password.encode("utf-8"),
        base64.b64decode(key_derivation_method.salt),
        key_derivation_method.iterations,
    )

    async with Itgs() as itgs:
        conn = await itgs.conn()
        cursor = conn.cursor()
        now = time.time()
        result = await cursor.execute(
            """
            INSERT INTO direct_accounts (
                uid,
                email,
                key_derivation_method,
                derived_password,
                created_at,
                email_verified_at
            ) 
            SELECT
                ?, ?, ?, ?, ?, ?
            WHERE
                NOT EXISTS (
                    SELECT 1 FROM direct_accounts AS da WHERE da.email = ?
                )
            """,
            (
                uid,
                email,
                key_derivation_method.json(),
                base64.b64encode(derived_password).decode("ascii"),
                now,
                now if email_verified else None,
                email,
            ),
        )
        if result.rows_affected is None or result.rows_affected < 1:
            logger.warning(f"An account with email {email} already exists")
            return
        logger.info(f"Created account with email {email} and indicated password")


if __name__ == "__main__":
    main()
