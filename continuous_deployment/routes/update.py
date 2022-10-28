from fastapi import APIRouter, Header, Response
from pydantic import BaseModel, Field
from typing import Literal, Optional
from models import (
    AUTHORIZATION_INVALID_PREFIX,
    AUTHORIZATION_NOT_SET,
    AUTHORIZATION_UNKNOWN_TOKEN,
    STANDARD_ERRORS_BY_CODE,
)
import os
import hmac
from itgs import Itgs

router = APIRouter()


class UpdateArgs(BaseModel):
    repo: Literal["backend", "websocket", "frontend-web", "jobs"] = Field(
        description="the repository identifier that was updated",
    )


@router.post(
    "/update",
    status_code=202,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def update(args: UpdateArgs, authorization: Optional[str] = Header(None)):
    """Triggers deployment of the latest version of the given repository.
    Authorization must be of the form 'token <token>' where token is the shared
    deployment secret
    """
    if authorization is None:
        return AUTHORIZATION_NOT_SET
    if not authorization.startswith("token "):
        return AUTHORIZATION_INVALID_PREFIX
    token = authorization[len("token ") :]
    if not hmac.compare_digest(token, os.environ["DEPLOYMENT_SECRET"]):
        return AUTHORIZATION_UNKNOWN_TOKEN

    async with Itgs() as itgs:
        redis = await itgs.redis()
        await redis.publish(f"updates:{args.repo}", "1")

    return Response(status_code=202)
