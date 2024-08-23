from enum import IntFlag, auto


class InstructorFlags(IntFlag):
    SHOWS_IN_ADMIN = auto()
    """Unset to hide the instructor in the admin area by default"""

    SHOWS_IN_CLASSES_FILTER = auto()
    """Unset to prevent the instructor from showing in the classes filter"""


ALL_INSTRUCTOR_FLAGS = (
    InstructorFlags.SHOWS_IN_ADMIN | InstructorFlags.SHOWS_IN_CLASSES_FILTER
)
