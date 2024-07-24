from pydantic import BaseModel, Field
from typing import Optional
from resources.filter_item import FilterItemModel


class ClientFlowPredicate(BaseModel):
    version: Optional[FilterItemModel[int]] = Field(
        None, description="the client-provided android version code they want to match"
    )


def check_flow_predicate(
    rule: ClientFlowPredicate,
    /,
    *,
    version: Optional[int],
) -> bool:
    """Checks if the given client flow rule matches the available information"""
    if rule.version is not None and not rule.version.to_result().check_constant(
        version
    ):
        return False
    return True
