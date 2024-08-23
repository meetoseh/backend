import secrets
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, StringConstraints
from typing import Optional, Annotated
from auth import auth_admin
from instructors.lib.instructor_flags import InstructorFlags
from itgs import Itgs
from models import STANDARD_ERRORS_BY_CODE
import instructors.lib.stats


router = APIRouter()


class CreateInstructorRequest(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] = (
        Field(description="The display name for the instructor")
    )
    bias: float = Field(
        description=(
            "A non-negative number generally less than 1 that influences "
            "content selection towards this instructor."
        ),
        ge=0,
    )


class CreateInstructorResponse(BaseModel):
    uid: str = Field(description="The unique identifier for the instructor")
    name: str = Field(description="The display name for the instructor")
    bias: float = Field(description="The bias for the instructor")
    created_at: float = Field(
        description=(
            "The timestamp of when the instructor was created, specified in "
            "seconds since the unix epoch"
        )
    )
    flags: int = Field(
        description=(
            "The flags for the instructor, which is a bitfield. From least to most "
            "significant:\n"
            " - 0x01: unset to prevent the instructor from being shown by default in the admin area\n"
            " - 0x02: unset to prevent the instructor from being shown in the classes filter\n"
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
        if auth_result.result is None:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor("none")

        now = time.time()
        uid = f"oseh_i_{secrets.token_urlsafe(16)}"
        flags = int(InstructorFlags.SHOWS_IN_ADMIN)

        await cursor.execute(
            """
            INSERT INTO instructors (
                uid, name, bias, flags, created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (uid, args.name, args.bias, flags, now),
        )

        await instructors.lib.stats.on_instructor_created(itgs, created_at=now)
        return Response(
            content=CreateInstructorResponse(
                uid=uid, name=args.name, bias=args.bias, flags=flags, created_at=now
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=201,
        )
