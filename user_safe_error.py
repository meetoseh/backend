from fastapi.responses import Response


class UserSafeError(Exception):
    """An error that is safe to show to the user"""

    def __init__(self, message: str, response: Response):
        self.message = message
        """A short description of the error which may not be safe to share publicly"""

        self.response = response
        """The error response which is safe to share publicly"""
