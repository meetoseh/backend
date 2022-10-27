"""A collection of apis for working with UIDs, which are string unique identifiers
as if by secrets.token_urlsafe()
"""


def is_safe_uid(uid: str) -> bool:
    """Determines if the given uid looks like a standard uid, ie., it's not empty or
    excessively long and it has urlsafe characters.
    """
    if not uid:
        return False
    if len(uid) > 155:
        return False
    return all(
        c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
        for c in uid
    )
