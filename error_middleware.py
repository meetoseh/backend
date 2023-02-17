from typing import Optional
from fastapi import Request, Response
from fastapi.responses import PlainTextResponse
from itgs import Itgs
import traceback
import socket


async def handle_request_error(request: Request, exc: Exception) -> Response:
    """Handles an error while processing a request"""
    await handle_error(exc)
    return PlainTextResponse(content="internal server error", status_code=500)


async def handle_error(exc: Exception, *, extra_info: Optional[str] = None) -> None:
    """Handles a generic request, potentially outside of the request context"""
    traceback.print_exception(type(exc), exc, exc.__traceback__)

    message = "\n".join(
        traceback.format_exception(type(exc), exc, exc.__traceback__)[-5:]
    )
    message = f"{socket.gethostname()}\n\n```\n{message}\n```"

    if extra_info is not None:
        message += f"\n\n{extra_info}"

    async with Itgs() as itgs:
        slack = await itgs.slack()
        await slack.send_web_error_message(message, "an error occurred in backend")
