from enum import Enum
from typing import Literal


class NotSetEnum(Enum):
    NOT_SET = "NOT_SET"


NotSet = Literal[NotSetEnum.NOT_SET]
