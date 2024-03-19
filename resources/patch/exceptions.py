from typing import Generic, Literal, TypeVar
from fastapi.responses import Response

from models import StandardErrorResponse

T = TypeVar("T", bound=str)


class PreconditionFailedException(Exception):
    """Used to indicate that a precondition for a request was not met."""

    def __init__(self, field: str, expected: str, actual: str):
        super().__init__(f"expected {field!r} to be {expected}, but was {actual}")
        self.field = field
        self.expected = expected
        self.actual = actual


class SubresourceMissingException(Exception, Generic[T]):
    """Used to indicate that the request required a subresource to exist, but it did not."""

    def __init__(self, err_type: T, field: str, uid: str):
        super().__init__(f"no {field!r} with UID {uid!r}")
        self.err_type: T = err_type
        self.field = field
        self.uid = uid

    def to_response(self) -> Response:
        resource_name = self.err_type
        if resource_name.endswith("_not_found"):
            resource_name = resource_name[: -len("_not_found")]
        return Response(
            status_code=404,
            content=StandardErrorResponse[T](
                type=self.err_type,
                message=f"there is no {resource_name} with that UID",
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )


class ConflictException(Exception, Generic[T]):
    def __init__(self, err_type: T, field: str, other_uid: str, err_response: Response):
        super().__init__(f"{field!r} is in conflict with {other_uid!r}")
        self.err_type: T = err_type
        self.field = field
        self.other_uid = other_uid
        self.err_response = err_response

    def to_response(self) -> Response:
        return self.err_response


class UpdateFailedException(Exception):
    """Used to indicate that we didnt find a cause for why the update failed, but it did"""

    def __init__(self) -> None:
        super().__init__("the home screen image could not be updated")

    def to_response(self) -> Response:
        return Response(
            status_code=500,
            content=StandardErrorResponse[Literal["internal_error"]](
                type="internal_error",
                message="the resource could not be updated",
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
