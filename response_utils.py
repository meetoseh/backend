from fastapi.responses import Response, StreamingResponse
from typing import Literal, Optional, overload
import io


@overload
async def response_to_bytes(response: Literal[None]) -> None:
    ...


@overload
async def response_to_bytes(response: Response) -> bytes:
    ...


async def response_to_bytes(response: Optional[Response]) -> Optional[bytes]:
    """Converts a fastapi response object to the corresponding bytes. This supports
    standard responses, the text responses, and streaming responses.

    This is typically used when we want to simulate internal api calls but
    do not want to couple function signatures, or when we cache entire responses
    but sometimes we need to access the bytes directly.
    """

    if response is None:
        return None

    if isinstance(response, StreamingResponse):
        writer = io.BytesIO()
        async for chunk in response.body_iterator:
            if isinstance(chunk, str):
                chunk = chunk.encode("utf-8")
            writer.write(chunk)
        return writer.getvalue()

    return response.body


async def cleanup_response(response: Response) -> None:
    """If necessary, closes handles on the given fastapi response object. Useful when we fetch
    a cached response optimistically, but later might decide not to return it.

    Args:
        response (Response): The fastapi response object to clean up.
    """
    if isinstance(response, StreamingResponse) and hasattr(
        response.body_iterator, "aclose"
    ):
        await response.body_iterator.aclose()  # type: ignore
