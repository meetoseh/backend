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
    if not authorization.startswith("bearer "):
        return AUTHORIZATION_INVALID_PREFIX
    token = authorization[len("bearer ") :]
    if not hmac.compare_digest(token, os.environ["DEPLOYMENT_SECRET"]):
        return AUTHORIZATION_UNKNOWN_TOKEN

    async with Itgs() as itgs:
        redis = await itgs.redis()
        num_subscribers = await redis.publish(f"updates:{args.repo}", "1")
    
        slack = await itgs.slack()
        if num_subscribers != 2:
            await slack.send_web_error_message(
                f"When updating {args.repo=}, there were {num_subscribers=} subscribers! Expected 2.",
                f"{args.repo} update failed"
            )
        else:
            await slack.send_ops_message(
                f"Updated {args.repo}: {num_subscribers} instances received update request.",
                f"{args.repo} updated"
            )

    return Response(status_code=202)
