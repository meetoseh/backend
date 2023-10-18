import secrets
import base64
from typing import Literal

from pydantic import BaseModel, Field


class KeyDerivationMethod(BaseModel):
    name: Literal["pbkdf2_hmac"] = Field(description="The name of the method")
    hash_name: Literal["sha1", "sha256", "sha512"] = Field(
        description="The name of the hash function"
    )
    salt: str = Field(description="The salt used to derive the key", min_length=32)
    iterations: int = Field(description="The number of iterations to use", ge=100_000)

    @property
    def salt_bytes(self) -> bytes:
        return base64.b64decode(self.salt)


def create_new_key_derivation_method() -> KeyDerivationMethod:
    """Creates a new key derivation method with a random salt."""
    return KeyDerivationMethod(
        name="pbkdf2_hmac",
        hash_name="sha512",
        salt=base64.b64encode(secrets.token_bytes(32)).decode("ascii"),
        iterations=210_000,
    )


def is_satisfactory_key_derivation_method(method: KeyDerivationMethod) -> bool:
    """Determines if the given key derivation method is at least as secure
    as the method we use for new users.
    """
    return (
        method.name == "pbkdf2_hmac"
        and method.hash_name == "sha512"
        and method.iterations >= 210_000
    )
