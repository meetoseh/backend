from typing import Optional
from fastapi import Request, Response
from fastapi.responses import PlainTextResponse
import traceback
import socket
from loguru import logger
import io


async def handle_request_error(request: Request, exc: Exception) -> Response:
    """Handles an error while processing a request"""
    await handle_error(exc)
    return PlainTextResponse(content="internal server error", status_code=500)


async def handle_error(exc: Exception, *, extra_info: Optional[str] = None) -> None:
    """Handles a generic request, potentially outside of the request context"""
    full_exc = io.StringIO()
    full_exc.write(f"{extra_info=}\n")
    traceback.print_exception(type(exc), exc, exc.__traceback__, file=full_exc)
    logger.error(full_exc.getvalue())

    message = "\n".join(
        traceback.format_exception(type(exc), exc, exc.__traceback__)[-5:]
    )
    message = f"{socket.gethostname()}\n\n```\n{message}\n```"

    if extra_info is not None:
        message += f"\n\n{extra_info}"

    from itgs import Itgs

    async with Itgs() as itgs:
        slack = await itgs.slack()
        await slack.send_web_error_message(message, "an error occurred in backend")


async def handle_contextless_error(*, extra_info: Optional[str] = None) -> None:
    """Handles an error that was found programmatically, i.e., which didn't cause an
    actual exception object to be raised. This will produce a stack trace and include
    the extra information.
    """
    full_exc = io.StringIO()
    full_exc.write(f"{extra_info=}\n")
    traceback.print_stack(file=full_exc)
    logger.error(full_exc.getvalue())

    current_traceback = traceback.extract_stack()[-5:]
    message = "\n".join(traceback.format_list(current_traceback))
    message = f"{socket.gethostname()}\n\n```\n{message}\n```"

    if extra_info is not None:
        message += f"\n\n{extra_info}"

    from itgs import Itgs

    async with Itgs() as itgs:
        slack = await itgs.slack()
        await slack.send_web_error_message(
            message, "a contextless error occurred in backend"
        )
