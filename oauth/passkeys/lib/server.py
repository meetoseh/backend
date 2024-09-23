from typing import Dict
import fido2.server
import fido2.webauthn
import os
import urllib.parse

from visitors.lib.get_or_create_visitor import VisitorSource


def _make_fido2_server(rp_id: str) -> fido2.server.Fido2Server:
    return fido2.server.Fido2Server(
        fido2.webauthn.PublicKeyCredentialRpEntity(
            name="Oseh",
            id=rp_id,
        ),
        verify_origin=lambda origin: True,
    )


def _make_fido2_servers() -> Dict[VisitorSource, fido2.server.Fido2Server]:
    standard_server = _make_fido2_server("oseh.io")

    if os.environ["ENVIRONMENT"] != "production":
        root_backend_url = os.environ["ROOT_BACKEND_URL"]
        parsed_url = urllib.parse.urlparse(root_backend_url)
        backend_netloc = parsed_url.netloc
        return {
            "android": standard_server,
            "ios": standard_server,
            "browser": _make_fido2_server(backend_netloc),
        }

    return {
        "android": standard_server,
        "ios": standard_server,
        "browser": standard_server,
    }


FIDO2_SERVERS = _make_fido2_servers()
