from typing import Literal, Optional
import pem
import io
import cryptography.x509
import cryptography.hazmat.primitives
import cryptography.exceptions
import cryptography.hazmat.primitives.asymmetric.padding
import cryptography.hazmat.primitives.asymmetric.rsa
import cryptography.hazmat.primitives.hashes
import logging


def verify_signature(
    body_json: dict,
    decoded_signature: bytes,
    signing_certificate: pem.Certificate,
    signature_version: Literal["1", "2"],
    keys: list,
) -> Optional[str]:
    """Verifies that the given message body, already interpreted as JSON and
    determined to be a dict, is protected by the given signature, where the
    signature was signed by the private key associated with the given
    certificate.

    Only the specified keys within the body json are protected.

    https://docs.aws.amazon.com/sns/latest/dg/sns-verify-signature-of-message.html

    Args:
        body_json:
            The parsed JSON `dict` that was sent to us, presumably by
            Amazon (although this function intends to verify that).
        decoded_signature:
            The Signature from the `body_json`, decoded from base64.
        signing_certificate:
            The certificate from `SigningCertURL`, already downloaded
            and extracted.
        keys:
            The ordered keys which are protected by the signature within `body_json`.

    Returns:
        Either a `str`, which will be an error message that may be shown to the
        end-user explaining why the signature was rejected, or `None` if the
        signature is valid.
    """
    canonical_message = io.StringIO()
    for key in keys:
        val = body_json.get(key)
        if val is None:
            continue

        canonical_message.write(key)
        canonical_message.write("\n")
        canonical_message.write(str(val))
        canonical_message.write("\n")

    protected_message = str(canonical_message.getvalue())
    pem_certificate = signing_certificate.as_bytes()
    parsed_certificate = cryptography.x509.load_pem_x509_certificate(pem_certificate)
    public_key = parsed_certificate.public_key()

    assert isinstance(
        public_key, cryptography.hazmat.primitives.asymmetric.rsa.RSAPublicKey
    ), f"unknown amazon public key format: {type(public_key)}"

    try:
        public_key.verify(
            decoded_signature,
            protected_message.encode(),
            cryptography.hazmat.primitives.asymmetric.padding.PKCS1v15(),
            {
                "1": cryptography.hazmat.primitives.hashes.SHA1(),
                "2": cryptography.hazmat.primitives.hashes.SHA256(),
            }[signature_version],
        )
    except cryptography.exceptions.InvalidSignature:
        logging.warning("Signature verification failed", exc_info=True)
        return "Invalid Signature"

    return None
