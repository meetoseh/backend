class UpdatedDuringUpdateError(Exception):
    """Raised when an update is attempted while another update is in progress,
    and the update using a read-updateif flow. This is always retryable.
    """

    def __init__(self) -> None:
        super().__init__(
            "The underlying record was changed during the update, try again"
        )
