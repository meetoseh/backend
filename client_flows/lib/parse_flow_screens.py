import json
from typing import List, cast
from pydantic import TypeAdapter
import gzip
import base64
import hashlib

from lib.client_flows.client_flow_screen import ClientFlowScreen


adapter = cast(TypeAdapter[List[ClientFlowScreen]], TypeAdapter(List[ClientFlowScreen]))


def decode_flow_screens(raw: str) -> List[ClientFlowScreen]:
    """Decodes the raw string representation of a list of client flow screens as it
    is stored in the database to the internal representation.
    """
    return adapter.validate_json(gzip.decompress(base64.b85decode(raw)))


def encode_flow_screens(screens: List[ClientFlowScreen]) -> str:
    """Encodes the internal representation of a list of client flow screens to the raw
    string representation as it is stored in the database. This always produces the
    same value for the same input, at a significant cost in performance.
    """
    return base64.b85encode(
        gzip.compress(
            json.dumps(
                adapter.dump_python(screens, round_trip=True, exclude_none=True),
                sort_keys=True,
            ).encode("utf-8"),
            mtime=0,
            compresslevel=9,
        )
    ).decode("utf-8")


def etag_flow_screens(screens: List[ClientFlowScreen]) -> str:
    """Generates a strong etag for the given list of screens. Painfully slow."""
    return hashlib.sha512(
        json.dumps(
            adapter.dump_python(screens, round_trip=True), sort_keys=True
        ).encode("utf-8")
    ).hexdigest()
