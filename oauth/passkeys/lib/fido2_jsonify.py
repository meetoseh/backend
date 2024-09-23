from fido2.webauthn import PublicKeyCredentialCreationOptions
import base64


def credential_creation_options_to_client(
    options: PublicKeyCredentialCreationOptions,
) -> dict:
    assert options.extensions is None, options.extensions
    return {
        "rp": {"name": options.rp.name, "id": options.rp.id},
        "user": {
            "name": options.user.name,
            "id": options.user.id.decode("ascii"),
            "displayName": options.user.display_name,
        },
        "challenge": base64.urlsafe_b64encode(options.challenge).decode("ascii"),
        "pubKeyCredParams": [
            {"type": opt.type.value, "alg": opt.alg}
            for opt in options.pub_key_cred_params
        ],
        **({"timeout": options.timeout} if options.timeout is not None else {}),
        **(
            {
                "excludeCredentials": (
                    [
                        {
                            "type": cred.type.value,
                            "id": cred.id.decode("ascii"),
                            "transports": (
                                [t.value for t in cred.transports]
                                if cred.transports is not None
                                else None
                            ),
                        }
                        for cred in options.exclude_credentials
                    ]
                )
            }
            if options.exclude_credentials is not None
            else {}
        ),
        **(
            {
                "authenticatorSelection": (
                    {
                        "authenticatorAttachment": (
                            options.authenticator_selection.authenticator_attachment.value
                            if options.authenticator_selection.authenticator_attachment
                            is not None
                            else None
                        ),
                        "residentKey": (
                            options.authenticator_selection.resident_key.value
                            if options.authenticator_selection.resident_key is not None
                            else None
                        ),
                        "userVerification": (
                            options.authenticator_selection.user_verification.value
                            if options.authenticator_selection.user_verification
                            is not None
                            else None
                        ),
                    }
                )
            }
            if options.authenticator_selection is not None
            else {}
        ),
        **(
            {"attestation": (options.attestation.value)}
            if options.attestation is not None
            else {}
        ),
    }
