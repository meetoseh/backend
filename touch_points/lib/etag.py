import hashlib


def get_messages_etag(compressed_b85: str) -> str:
    """Returns the etag for messages with the given json-encoded, gzip-compressed, base85 string."""
    return hashlib.sha512(compressed_b85.encode("ascii")).hexdigest()
