from pydantic import BaseModel, Field
from typing import Optional
from resources.filter_item import FilterItemModel


class ClientFlowPredicate(BaseModel):
    version: Optional[FilterItemModel[int]] = Field(
        None,
        description="the client-provided android version code they want to match",
    )
    time_in_queue: Optional[FilterItemModel[int]] = Field(
        None,
        description="How long the client flow screen has been in the queue. Always zero at trigger time.",
    )
    account_age: Optional[FilterItemModel[int]] = Field(
        None,
        description="How long since the users account record was created, in seconds.",
    )


def check_flow_predicate(
    rule: ClientFlowPredicate,
    /,
    *,
    version: Optional[int],
    time_in_queue: int,
    account_age: int,
) -> bool:
    """Checks if the given client flow rule matches the available information"""
    if rule.version is not None and not rule.version.to_result().check_constant(
        version
    ):
        return False
    if (
        rule.time_in_queue is not None
        and not rule.time_in_queue.to_result().check_constant(time_in_queue)
    ):
        return False
    if rule.account_age is not None and not rule.account_age.to_result().check_constant(
        account_age
    ):
        return False
    return True
