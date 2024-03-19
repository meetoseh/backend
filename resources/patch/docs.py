from typing import Any, Dict, Literal, Union

from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse


PRECONDITION_DOCS = """The precondition for the update. The update will only go through
if for each explicitly set field in the precondition, the current
value of the field in the image being updated matches the value
set in the precondition.

Explicitly setting null in the precondition
will require the field is null in the image being updated, whereas
omitting a key in the precondition will allow any value in the course
being updated.
"""

PATCH_DOCS = """The patch to apply to the home screen image. Any explicitly set field in the
patch will be applied to the image being updated, provided the
precondition is met."""

ERROR_412_TYPES = Literal["precondition_failed"]


def create_responses(
    error_404_types: Any, error_409_types: Any = None
) -> Dict[Union[int, str], Dict[str, Any]]:
    return {
        "404": {
            "description": "a resource does not exist",
            "model": StandardErrorResponse[error_404_types],
        },
        **(
            {}
            if error_409_types is None
            else {
                "409": {
                    "description": "constraint violated",
                    "model": StandardErrorResponse[error_409_types],
                }
            }
        ),
        "412": {
            "description": "the precondition was not met",
            "model": StandardErrorResponse[ERROR_412_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    }


def create_description(resource: str) -> str:
    return f"""Patches the {resource} with the given UID, optionally restricted by the
given precondition.

If no patches are requested, the preconditions are checked atomically with
the read but there are no special freshness guarantees, i.e., we may verify
the preconditions against a state, and return a state, that was already
arbitrarily stale when the request was made.

If patches are requested and applied, then the preconditions are guarranteed
to have been valid when the patch was applied and the returned {resource}
was accurate at some point during the request, though the new state of the
{resource} may be stale by the time it is received by the client.

Requires standard authorization for an admin user.
"""
