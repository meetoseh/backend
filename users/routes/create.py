import secrets
import time
from typing import Optional
from fastapi import APIRouter, Header
from fastapi.responses import Response
from auth import auth_cognito
from itgs import Itgs
from models import STANDARD_ERRORS_BY_CODE

router = APIRouter()


@router.post("/", status_code=204, responses=STANDARD_ERRORS_BY_CODE)
async def create_user(authorization: Optional[str] = Header(None)):
    """Ensures a user exists in the users table, for bookkeeping purposes; must be
    called after successfully logging in with Amazon Cognito.

    This requires cognito authentication. You can read more about the forms of
    authentication at [/rest_auth.html](/rest_auth.html)
    """
    async with Itgs() as itgs:
        auth_result = await auth_cognito(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        # we assert since these would all be 5xx errors if they failed
        assert (
            auth_result.result.claims is not None
        ), "expected claims from auth_cognito"
        claims = auth_result.result.claims
        assert isinstance(claims.get("email"), str), "expected email in claims"

        name: Optional[str] = claims.get("name")
        given_name: Optional[str] = claims.get("given_name")
        family_name: Optional[str] = claims.get("family_name")

        if name is None and (given_name is not None or family_name is not None):
            name = " ".join([given_name or "", family_name or ""]).strip()

        if name is not None and (given_name is None or family_name is None):
            try:
                implied_given_name, implied_family_name = name.split(" ", 1)
            except ValueError:
                implied_given_name, implied_family_name = name, ""

            given_name = given_name or implied_given_name
            family_name = family_name or implied_family_name

        now = time.time()
        new_revenue_cat_id = f"oseh_u_rc_{secrets.token_urlsafe(16)}"
        conn = await itgs.conn()
        cursor = conn.cursor("none")
        response = await cursor.execute(
            """INSERT INTO users (
                sub,
                email,
                email_verified,
                phone_number,
                phone_number_verified,
                given_name,
                family_name,
                admin,
                revenue_cat_id,
                created_at
            )
            SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            WHERE NOT EXISTS (
                SELECT 1 FROM users
                WHERE users.sub = ?
            )""",
            (
                auth_result.result.sub,
                claims["email"],
                claims.get("email_verified", False),
                claims.get("phone_number"),
                claims.get("custom:pn_verified"),
                given_name,
                family_name,
                False,
                new_revenue_cat_id,
                now,
                auth_result.result.sub,
            ),
        )

        if response.rows_affected is not None and response.rows_affected > 0:
            jobs = await itgs.jobs()
            await jobs.enqueue(
                "runners.revenue_cat.ensure_user", user_sub=auth_result.result.sub
            )

        if "picture" in claims:
            jobs = await itgs.jobs()
            await jobs.enqueue(
                "runners.check_profile_picture",
                user_sub=auth_result.result.sub,
                picture_url=claims["picture"],
                jwt_iat=claims["iat"],
            )

        return Response(status_code=204)
