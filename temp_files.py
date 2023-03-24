from typing import Generator
from contextlib import contextmanager
import os
import secrets


def get_temp_file() -> str:
    """Gets a path to a random file which is in a folder that exists. This does not
    manage cleaning the file on your behalf
    """
    os.makedirs("tmp", exist_ok=True)
    return os.path.join("tmp", secrets.token_hex(16))


@contextmanager
def temp_file() -> Generator[str, None, None]:
    """Creates a temporary file and deletes it when done; yields the path to the file.

    This is lighter weight than the tempfile module, and is less secure, but it
    is generally easier for debugging, especially cross-platform.

    Stores the files in the `tmp` folder, which is created if it doesn't exist
    """
    tmp_file_loc = get_temp_file()
    try:
        yield tmp_file_loc
    finally:
        try:
            os.remove(tmp_file_loc)
        except FileNotFoundError:
            pass
