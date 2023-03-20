from itgs import Itgs
from typing import Literal, Optional
import secrets
import re


VALID_VISITOR_UID = re.compile(r"^oseh_v_[a-zA-Z0-9_-]{5,30}$")
VisitorSource = Literal["browser", "ios", "android"]


async def get_or_create_unsanitized_visitor(
    itgs: Itgs, *, visitor: Optional[str] = None, source: VisitorSource, seen_at: float
) -> str:
    """From a unverified, unsanitized visitor uid this either returns the
    visitor uid, if it appears valid, or creates a new visitor uid and
    returns that.

    The returned visitor uid is not necessarily valid, but it doesn't have
    any strange properties that could cause problems (excessively long,
    excessively short, containing invalid characters, etc.)

    Args:
        itgs (Itgs): The integrations to (re)use
        visitor (str or None): The uid of the visitor that was provided, or None
            to always create a new visitor
        source (VisitorSource): The client that the visitor was seen from
        seen_at (float): When the visitor was seen or the canonical time to create
            the visitor if the visitor has to be created.
    """
    if visitor is not None and VALID_VISITOR_UID.match(visitor) is not None:
        return visitor

    new_visitor = f"oseh_v_{secrets.token_urlsafe(16)}"

    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.execute(
        "INSERT INTO visitors (uid, version, source, created_at) VALUES (?, 1, ?, ?)",
        (new_visitor, source, seen_at),
    )
    return new_visitor
