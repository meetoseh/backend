import secrets
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, constr
from typing import Optional
from auth import auth_admin
from itgs import Itgs
from models import STANDARD_ERRORS_BY_CODE
import instructors.lib.stats


router = APIRouter()


class CreateInstructorRequest(BaseModel):
    name: constr(strip_whitespace=True, min_length=1) = Field(
        description="The display name for the instructor"
    )


class CreateInstructorResponse(BaseModel):
    uid: str = Field(description="The unique identifier for the instructor")
    name: str = Field(description="The display name for the instructor")
    created_at: float = Field(
        description=(
            "The timestamp of when the instructor was created, specified in "
            "seconds since the unix epoch"
        )
    )


@router.post(
    "/",
    response_model=CreateInstructorResponse,
    responses=STANDARD_ERRORS_BY_CODE,
    status_code=201,
)
async def create_instructor(
    args: CreateInstructorRequest, authorization: Optional[str] = Header(None)
):
    """Creates a new instructor with the given name. There is no requirement
    that instructor names be unique, though that's typically desirable to avoid
    confusion.

    This requires standard authentication and can only be done by admin users.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor("none")

        now = time.time()
        uid = f"oseh_i_{secrets.token_urlsafe(16)}"

        await cursor.execute(
            """
            INSERT INTO instructors (
                uid, name, created_at
            )
            VALUES (?, ?, ?)
            """,
            (uid, args.name, now),
        )

        await instructors.lib.stats.on_instructor_created(itgs, created_at=now)
        return Response(
            content=CreateInstructorResponse(
                uid=uid, name=args.name, created_at=now
            ).json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=201,
        )
