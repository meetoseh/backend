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
        assert isinstance(claims.get("given_name"), str), "expected given_name in claims"
        assert isinstance(claims.get("family_name"), str) in claims, "expected family_name in claims"

        now = time.time()
        conn = await itgs.conn()
        cursor = conn.cursor("none")
        await cursor.execute(
            """INSERT INTO users (
                sub,
                email,
                given_name,
                family_name,
                created_at
            )
            SELECT ?, ?, ?, ?, ?
            WHERE NOT EXISTS (
                SELECT 1 FROM users
                WHERE users.sub = ?
            )""",
            (
                auth_result.result.sub,
                claims["email"],
                claims["given_name"],
                claims["family_name"],
                now,
                auth_result.result.sub,
            ),
        )

        if "picture" in claims:
            jobs = await itgs.jobs()
            await jobs.enqueue(
                "runners.check_profile_picture",
                user_sub=auth_result.result.sub,
                picture_url=claims["picture"],
            )

        return Response(status_code=204)
